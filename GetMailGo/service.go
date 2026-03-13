package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"time"
)

var whitespacePattern = regexp.MustCompile(`\s+`)

var verificationCodePatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)Verification code:?\s*(\d{6})`),
	regexp.MustCompile(`(?i)code is\s*(\d{6})`),
	regexp.MustCompile(`代码为[:：]?\s*(\d{6})`),
	regexp.MustCompile(`验证码[:：]?\s*(\d{6})`),
	regexp.MustCompile(`>\s*(\d{6})\s*<`),
	regexp.MustCompile(`(?i)\b(\d{6})\b`),
}

type MailboxLookupRequest struct {
	MailToken string `json:"mail_token"`
	Timeout   *int   `json:"timeout"`
	Limit     *int   `json:"limit"`
}

type MessageSummary struct {
	ID               *string `json:"id"`
	Subject          string  `json:"subject"`
	From             string  `json:"from"`
	To               string  `json:"to"`
	ReceivedAt       *string `json:"received_at"`
	VerificationCode *string `json:"verification_code"`
	Preview          string  `json:"preview"`
}

type MailboxLookupResponse struct {
	Status           string           `json:"status"`
	Email            string           `json:"email"`
	VerificationCode *string          `json:"verification_code"`
	LatestSubject    string           `json:"latest_subject"`
	LatestReceivedAt *string          `json:"latest_received_at"`
	LatestMessageID  *string          `json:"latest_message_id"`
	MessageCount     int              `json:"message_count"`
	Messages         []MessageSummary `json:"messages"`
	Message          string           `json:"message"`
	Hint             string           `json:"hint"`
	PolledSeconds    float64          `json:"polled_seconds"`
}

type HealthResponse struct {
	Status            string `json:"status"`
	ProjectRoot       string `json:"project_root"`
	ResendAPIBase     string `json:"resend_api_base"`
	ResendDomain      string `json:"resend_domain"`
	ReceivingReady    bool   `json:"receiving_ready"`
	TokenSecretSource string `json:"token_secret_source"`
}

type MailService struct {
	cfg               Config
	client            *http.Client
	tokenSecret       []byte
	tokenSecretSource string
}

func NewMailService(cfg Config, tokenSecret []byte, tokenSecretSource string) *MailService {
	return &MailService{
		cfg:               cfg,
		client:            &http.Client{Timeout: 25 * time.Second},
		tokenSecret:       tokenSecret,
		tokenSecretSource: tokenSecretSource,
	}
}

func (s *MailService) HealthSnapshot() HealthResponse {
	return HealthResponse{
		Status:            "ok",
		ProjectRoot:       s.cfg.BaseDir,
		ResendAPIBase:     s.cfg.ResendAPIBase,
		ResendDomain:      s.cfg.ResendDomain,
		ReceivingReady:    s.cfg.ResendAPIKey != "" && s.cfg.ResendDomain != "",
		TokenSecretSource: s.tokenSecretSource,
	}
}

func (s *MailService) LookupMailbox(ctx context.Context, mailToken string, timeoutSeconds int, limit int) (MailboxLookupResponse, error) {
	if strings.TrimSpace(mailToken) == "" {
		return MailboxLookupResponse{}, &ValidationError{Message: "mail_token 不能为空"}
	}
	if s.cfg.ResendAPIKey == "" || s.cfg.ResendDomain == "" {
		return MailboxLookupResponse{}, fmt.Errorf("缺少 RESEND_API_KEY 或 RESEND_DOMAIN 配置")
	}

	mailbox, err := resolveMailboxQueryToken(mailToken, s.tokenSecret)
	if err != nil {
		return MailboxLookupResponse{}, err
	}
	if mailbox.Email == "" {
		return MailboxLookupResponse{}, &ValidationError{Message: "mail_token 缺少邮箱地址"}
	}

	waitDuration := time.Duration(clampInt(timeoutSeconds, 0, 120)) * time.Second
	limit = clampInt(limit, 1, 20)
	startedAt := time.Now()
	deadline := startedAt.Add(waitDuration)

	var latestMessages []MessageSummary
	var latestTotalCount int
	var everSeenMessage bool

	for {
		rawMessages, err := s.fetchReceivedEmails(ctx, mailbox)
		if err != nil {
			return MailboxLookupResponse{}, err
		}

		latestTotalCount = len(rawMessages)
		everSeenMessage = everSeenMessage || len(rawMessages) > 0
		latestMessages = make([]MessageSummary, 0, min(limit, len(rawMessages)))
		for _, message := range rawMessages[:min(limit, len(rawMessages))] {
			latestMessages = append(latestMessages, s.buildMessageSummary(ctx, mailbox, message))
		}

		latestCode := firstVerificationCode(latestMessages)
		latestSubject := firstMessageSubject(latestMessages)
		latestReceivedAt := firstMessageReceivedAt(latestMessages)
		latestMessageID := firstMessageID(latestMessages)

		if latestCode != nil {
			return MailboxLookupResponse{
				Status:           "ok",
				Email:            mailbox.Email,
				VerificationCode: latestCode,
				LatestSubject:    latestSubject,
				LatestReceivedAt: latestReceivedAt,
				LatestMessageID:  latestMessageID,
				MessageCount:     latestTotalCount,
				Messages:         latestMessages,
				Message:          "已提取到最新验证码",
				Hint:             "",
				PolledSeconds:    roundToMillis(time.Since(startedAt).Seconds()),
			}, nil
		}

		if !time.Now().Before(deadline) {
			break
		}

		sleepFor := minDuration(3*time.Second, maxDuration(500*time.Millisecond, time.Until(deadline)))
		if sleepFor <= 0 {
			break
		}

		timer := time.NewTimer(sleepFor)
		select {
		case <-ctx.Done():
			timer.Stop()
			return MailboxLookupResponse{}, ctx.Err()
		case <-timer.C:
		}
	}

	hint := mailboxDebugHint(mailbox.Email, s.cfg.ResendDomain)
	message := "暂未收到任何邮件"
	if everSeenMessage {
		message = "已收到邮件，但暂未提取到 6 位验证码"
	}

	return MailboxLookupResponse{
		Status:           "pending",
		Email:            mailbox.Email,
		VerificationCode: nil,
		LatestSubject:    firstMessageSubject(latestMessages),
		LatestReceivedAt: firstMessageReceivedAt(latestMessages),
		LatestMessageID:  firstMessageID(latestMessages),
		MessageCount:     latestTotalCount,
		Messages:         latestMessages,
		Message:          message,
		Hint:             hint,
		PolledSeconds:    roundToMillis(time.Since(startedAt).Seconds()),
	}, nil
}

func (s *MailService) buildMessageSummary(ctx context.Context, mailbox MailboxHandle, message map[string]any) MessageSummary {
	messageID := stringValue(message["id"])
	var detail map[string]any
	if messageID != "" {
		fetched, err := s.fetchEmailDetail(ctx, messageID)
		if err == nil {
			detail = fetched
		}
	}

	payload := message
	if len(detail) > 0 {
		payload = detail
	}

	content := extractMessageContent(payload)
	code := extractVerificationCode(content)
	previewSeed := content
	if previewSeed == "" {
		previewSeed = stringValue(firstNonNil(message["subject"], payload["subject"]))
	}

	return MessageSummary{
		ID:               stringPtr(messageID),
		Subject:          strings.TrimSpace(stringValue(firstNonNil(message["subject"], payload["subject"]))),
		From:             formatAddress(firstNonNil(message["from"], payload["from"])),
		To:               formatAddress(firstNonNil(message["to"], payload["to"])),
		ReceivedAt:       stringPtr(strings.TrimSpace(stringValue(firstNonNil(message["created_at"], payload["created_at"])))),
		VerificationCode: stringPtr(code),
		Preview:          compactText(previewSeed, 260),
	}
}

func (s *MailService) fetchReceivedEmails(ctx context.Context, mailbox MailboxHandle) ([]map[string]any, error) {
	if mailbox.Email == "" {
		return nil, nil
	}

	query := url.Values{}
	query.Set("limit", "100")
	endpoint := s.cfg.ResendAPIBase + "/emails/receiving?" + query.Encode()

	body, statusCode, err := s.doJSONRequest(ctx, http.MethodGet, endpoint)
	if err != nil {
		return nil, err
	}
	if statusCode != http.StatusOK {
		return nil, describeResendError(statusCode, body)
	}

	var response struct {
		Data []map[string]any `json:"data"`
	}
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("解析 Resend 邮件列表失败: %w", err)
	}

	createdFloor := maxFloat(0, mailbox.CreatedAt-30)
	filtered := make([]map[string]any, 0, len(response.Data))
	for _, message := range response.Data {
		if !messageTargetsMailbox(message, mailbox.Email) {
			continue
		}
		createdAt := parseResendCreatedAt(message["created_at"])
		if createdAt > 0 && createdAt < createdFloor {
			continue
		}
		filtered = append(filtered, message)
	}

	slices.SortFunc(filtered, func(a, b map[string]any) int {
		left := parseResendCreatedAt(a["created_at"])
		right := parseResendCreatedAt(b["created_at"])
		switch {
		case left > right:
			return -1
		case left < right:
			return 1
		default:
			return 0
		}
	})

	return filtered, nil
}

func (s *MailService) fetchEmailDetail(ctx context.Context, messageID string) (map[string]any, error) {
	if strings.TrimSpace(messageID) == "" {
		return nil, nil
	}

	endpoint := s.cfg.ResendAPIBase + "/emails/receiving/" + url.PathEscape(messageID)
	body, statusCode, err := s.doJSONRequest(ctx, http.MethodGet, endpoint)
	if err != nil {
		return nil, err
	}
	if statusCode != http.StatusOK {
		return nil, describeResendError(statusCode, body)
	}

	var wrapper struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(body, &wrapper); err == nil && len(wrapper.Data) > 0 {
		return wrapper.Data, nil
	}

	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, fmt.Errorf("解析 Resend 邮件详情失败: %w", err)
	}
	return payload, nil
}

func (s *MailService) doJSONRequest(ctx context.Context, method string, endpoint string) ([]byte, int, error) {
	reqCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(reqCtx, method, endpoint, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+s.cfg.ResendAPIKey)

	resp, err := s.client.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("Resend Receiving API 连接失败: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, resp.StatusCode, fmt.Errorf("读取 Resend 响应失败: %w", err)
	}
	return body, resp.StatusCode, nil
}

func describeResendError(statusCode int, body []byte) error {
	detail := strings.TrimSpace(string(bytes.TrimSpace(body)))
	if len(detail) > 240 {
		detail = detail[:240]
	}
	if statusCode == http.StatusUnauthorized && (strings.Contains(detail, "restricted_api_key") || strings.Contains(detail, "only send emails")) {
		return fmt.Errorf("当前 RESEND_API_KEY 仅支持发信，不支持 Receiving API。请在 Resend 后台创建具备读取入站邮件权限的 API Key。")
	}
	return fmt.Errorf("Resend Receiving API 校验失败: HTTP %d %s", statusCode, detail)
}

func compactText(value string, limit int) string {
	text := strings.TrimSpace(whitespacePattern.ReplaceAllString(value, " "))
	if text == "" {
		return ""
	}
	if len([]rune(text)) <= limit {
		return text
	}
	runes := []rune(text)
	return strings.TrimSpace(string(runes[:limit])) + "..."
}

func formatAddress(value any) string {
	switch typed := value.(type) {
	case string:
		return strings.TrimSpace(typed)
	case map[string]any:
		email := strings.TrimSpace(stringValue(firstNonNil(typed["email"], typed["address"])))
		name := strings.TrimSpace(stringValue(typed["name"]))
		if name != "" && email != "" && name != email {
			return name + " <" + email + ">"
		}
		if email != "" {
			return email
		}
		return name
	case []any:
		parts := make([]string, 0, len(typed))
		for _, item := range typed {
			formatted := formatAddress(item)
			if formatted != "" {
				parts = append(parts, formatted)
			}
		}
		return strings.Join(parts, ", ")
	default:
		return ""
	}
}

func extractMessageContent(detail map[string]any) string {
	parts := []string{
		stringValue(detail["text"]),
		stringValue(detail["html"]),
		stringValue(detail["raw"]),
		stringValue(detail["content"]),
	}
	for _, key := range []string{"headers", "attachments"} {
		if value, ok := detail[key]; ok && value != nil {
			if raw, err := json.Marshal(value); err == nil {
				parts = append(parts, string(raw))
			}
		}
	}

	output := make([]string, 0, len(parts))
	for _, part := range parts {
		if strings.TrimSpace(part) != "" {
			output = append(output, part)
		}
	}
	return strings.Join(output, "\n")
}

func extractVerificationCode(emailContent string) string {
	if strings.TrimSpace(emailContent) == "" {
		return ""
	}
	for index, pattern := range verificationCodePatterns {
		matches := pattern.FindAllStringSubmatchIndex(emailContent, -1)
		for _, match := range matches {
			if len(match) < 4 {
				continue
			}
			code := emailContent[match[2]:match[3]]
			if code == "177010" {
				continue
			}
			if index == len(verificationCodePatterns)-1 {
				if match[2] > 0 {
					previous := emailContent[match[2]-1]
					if previous == '#' || previous == '&' {
						continue
					}
				}
			}
			return code
		}
	}
	return ""
}

func parseResendCreatedAt(raw any) float64 {
	text := strings.TrimSpace(stringValue(raw))
	if text == "" {
		return 0
	}
	timestamp, err := time.Parse(time.RFC3339Nano, text)
	if err != nil {
		return 0
	}
	return float64(timestamp.UnixNano()) / float64(time.Second)
}

func messageTargetsMailbox(message map[string]any, mailboxEmail string) bool {
	target := strings.TrimSpace(strings.ToLower(mailboxEmail))
	if target == "" {
		return false
	}

	switch recipients := message["to"].(type) {
	case string:
		return strings.TrimSpace(strings.ToLower(recipients)) == target
	case []any:
		for _, item := range recipients {
			switch typed := item.(type) {
			case string:
				if strings.TrimSpace(strings.ToLower(typed)) == target {
					return true
				}
			case map[string]any:
				address := strings.TrimSpace(strings.ToLower(stringValue(firstNonNil(typed["email"], typed["address"]))))
				if address == target {
					return true
				}
			}
		}
	case map[string]any:
		address := strings.TrimSpace(strings.ToLower(stringValue(firstNonNil(recipients["email"], recipients["address"]))))
		return address == target
	}
	return false
}

func mailboxDebugHint(email string, resendDomain string) string {
	domain := normalizeResendDomain(email)
	if strings.Contains(domain, "@") {
		domain = normalizeResendDomain(domain)
	}
	if strings.HasSuffix(domain, ".resend.app") {
		return "Resend Receiving API 当前未看到发给 " + email + " 的入站邮件。这个地址属于 Resend 托管接收域，通常不需要你自己再配 MX。请确认验证码邮件确实发到了这个完整地址，并检查 Resend 后台该 receiving domain 是否可用。"
	}
	if domain == "" {
		domain = resendDomain
	}
	return "Resend Receiving API 当前未看到发给 " + email + " 的入站邮件。这通常说明邮件被你现有邮箱服务收到了，但没有进入 Resend。如果根域已经有自己的 MX，按 Resend 文档更推荐使用子域做收件，或者在现有邮箱服务里把该地址/catch-all 转发到 Resend。"
}

func firstVerificationCode(messages []MessageSummary) *string {
	for _, item := range messages {
		if item.VerificationCode != nil && *item.VerificationCode != "" {
			return item.VerificationCode
		}
	}
	return nil
}

func firstMessageSubject(messages []MessageSummary) string {
	if len(messages) == 0 {
		return ""
	}
	return messages[0].Subject
}

func firstMessageReceivedAt(messages []MessageSummary) *string {
	if len(messages) == 0 {
		return nil
	}
	return messages[0].ReceivedAt
}

func firstMessageID(messages []MessageSummary) *string {
	if len(messages) == 0 {
		return nil
	}
	return messages[0].ID
}

func stringValue(value any) string {
	switch typed := value.(type) {
	case nil:
		return ""
	case string:
		return typed
	case json.Number:
		return typed.String()
	case float64:
		return fmt.Sprintf("%v", typed)
	case float32:
		return fmt.Sprintf("%v", typed)
	case int:
		return fmt.Sprintf("%d", typed)
	case int64:
		return fmt.Sprintf("%d", typed)
	case bool:
		if typed {
			return "true"
		}
		return "false"
	default:
		return ""
	}
}

func stringPtr(value string) *string {
	text := strings.TrimSpace(value)
	if text == "" {
		return nil
	}
	return &text
}

func clampInt(value int, minValue int, maxValue int) int {
	if value < minValue {
		return minValue
	}
	if value > maxValue {
		return maxValue
	}
	return value
}

func firstNonNil(values ...any) any {
	for _, value := range values {
		if value != nil {
			return value
		}
	}
	return nil
}

func min(a int, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxFloat(a float64, b float64) float64 {
	if a > b {
		return a
	}
	return b
}

func minDuration(a time.Duration, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}

func maxDuration(a time.Duration, b time.Duration) time.Duration {
	if a > b {
		return a
	}
	return b
}
