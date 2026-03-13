package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type Config struct {
	Host          string `json:"-"`
	Port          int    `json:"-"`
	ResendAPIBase string `json:"resend_api_base"`
	ResendAPIKey  string `json:"resend_api_key"`
	ResendDomain  string `json:"resend_domain"`
	ConfigPath    string `json:"-"`
	BaseDir       string `json:"-"`
}

func defaultConfig() Config {
	return Config{
		Host:          "0.0.0.0",
		Port:          8021,
		ResendAPIBase: "https://api.resend.com",
	}
}

func loadConfig() (Config, error) {
	cfg := defaultConfig()
	configPath, err := discoverConfigPath()
	if err != nil {
		return cfg, err
	}
	if configPath != "" {
		if err := mergeConfigFile(&cfg, configPath); err != nil {
			return cfg, err
		}
		cfg.ConfigPath = configPath
		cfg.BaseDir = filepath.Dir(configPath)
	}
	if cfg.BaseDir == "" {
		cfg.BaseDir, err = defaultBaseDir()
		if err != nil {
			return cfg, err
		}
	}

	if value := strings.TrimSpace(os.Getenv("GETMAIL_HOST")); value != "" {
		cfg.Host = value
	}
	if value := strings.TrimSpace(os.Getenv("GETMAIL_PORT")); value != "" {
		port, err := strconv.Atoi(value)
		if err != nil {
			return cfg, fmt.Errorf("GETMAIL_PORT 无效: %w", err)
		}
		cfg.Port = port
	}
	if value := strings.TrimSpace(os.Getenv("RESEND_API_BASE")); value != "" {
		cfg.ResendAPIBase = value
	}
	if value := strings.TrimSpace(os.Getenv("RESEND_API_KEY")); value != "" {
		cfg.ResendAPIKey = value
	}
	if value := strings.TrimSpace(os.Getenv("RESEND_DOMAIN")); value != "" {
		cfg.ResendDomain = value
	}

	cfg.ResendAPIBase = strings.TrimRight(strings.TrimSpace(cfg.ResendAPIBase), "/")
	cfg.ResendDomain = normalizeResendDomain(cfg.ResendDomain)
	cfg.ResendAPIKey = strings.TrimSpace(cfg.ResendAPIKey)

	return cfg, nil
}

func mergeConfigFile(cfg *Config, path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("读取 config.json 失败: %w", err)
	}

	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		return fmt.Errorf("解析 config.json 失败: %w", err)
	}

	if value, ok := raw["resend_api_base"].(string); ok && strings.TrimSpace(value) != "" {
		cfg.ResendAPIBase = value
	}
	if value, ok := raw["resend_api_key"].(string); ok && strings.TrimSpace(value) != "" {
		cfg.ResendAPIKey = value
	}
	if value, ok := raw["resend_domain"].(string); ok && strings.TrimSpace(value) != "" {
		cfg.ResendDomain = value
	}
	if value, ok := raw["getmail_host"].(string); ok && strings.TrimSpace(value) != "" {
		cfg.Host = value
	}
	if value, ok := raw["getmail_port"]; ok {
		switch typed := value.(type) {
		case float64:
			cfg.Port = int(typed)
		case string:
			port, err := strconv.Atoi(strings.TrimSpace(typed))
			if err != nil {
				return fmt.Errorf("config.json 中 getmail_port 无效: %w", err)
			}
			cfg.Port = port
		}
	}

	return nil
}

func discoverConfigPath() (string, error) {
	if explicit := strings.TrimSpace(os.Getenv("GETMAIL_CONFIG")); explicit != "" {
		return filepath.Abs(explicit)
	}

	for _, candidate := range configCandidates() {
		if candidate == "" {
			continue
		}
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate, nil
		}
	}
	return "", nil
}

func configCandidates() []string {
	candidates := []string{}
	if cwd, err := os.Getwd(); err == nil {
		candidates = append(candidates, filepath.Join(cwd, "config.json"))
	}
	if exeDir, err := executableDir(); err == nil {
		candidates = append(candidates, filepath.Join(exeDir, "config.json"))
	}
	return uniquePaths(candidates)
}

func loadTokenSecret(cfg Config) ([]byte, string, error) {
	if envSecret := strings.TrimSpace(os.Getenv("MAILBOX_QUERY_TOKEN_SECRET")); envSecret != "" {
		return []byte(envSecret), "env", nil
	}

	secretPath, err := discoverSecretPath(cfg.BaseDir)
	if err != nil {
		return nil, "", err
	}
	if secretPath == "" {
		return nil, "", errors.New("无法定位 .mailbox_query_token_secret")
	}

	if data, err := os.ReadFile(secretPath); err == nil {
		secret := strings.TrimSpace(string(data))
		if secret != "" {
			return []byte(secret), "file", nil
		}
	}

	generated, err := generateURLSafeSecret(48)
	if err != nil {
		return nil, "", fmt.Errorf("生成 MAILBOX_QUERY_TOKEN_SECRET 失败: %w", err)
	}
	if err := os.WriteFile(secretPath, []byte(generated), 0o600); err != nil {
		return nil, "", fmt.Errorf("写入 .mailbox_query_token_secret 失败: %w", err)
	}
	return []byte(generated), "file", nil
}

func discoverSecretPath(baseDir string) (string, error) {
	if explicit := strings.TrimSpace(os.Getenv("MAILBOX_QUERY_TOKEN_SECRET_FILE")); explicit != "" {
		return filepath.Abs(explicit)
	}

	candidates := []string{}
	if baseDir != "" {
		candidates = append(candidates, filepath.Join(baseDir, ".mailbox_query_token_secret"))
	}
	if cwd, err := os.Getwd(); err == nil {
		candidates = append(candidates, filepath.Join(cwd, ".mailbox_query_token_secret"))
	}
	if exeDir, err := executableDir(); err == nil {
		candidates = append(candidates, filepath.Join(exeDir, ".mailbox_query_token_secret"))
	}

	unique := uniquePaths(candidates)
	for _, candidate := range unique {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate, nil
		}
	}
	if len(unique) == 0 {
		return "", nil
	}
	return unique[0], nil
}

func generateURLSafeSecret(byteLen int) (string, error) {
	buf := make([]byte, byteLen)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}

func defaultBaseDir() (string, error) {
	if cwd, err := os.Getwd(); err == nil {
		return cwd, nil
	}
	return executableDir()
}

func executableDir() (string, error) {
	executable, err := os.Executable()
	if err != nil {
		return "", err
	}
	return filepath.Dir(executable), nil
}

func uniquePaths(paths []string) []string {
	seen := make(map[string]struct{}, len(paths))
	result := make([]string, 0, len(paths))
	for _, item := range paths {
		if item == "" {
			continue
		}
		abs, err := filepath.Abs(item)
		if err == nil {
			item = abs
		}
		if _, ok := seen[item]; ok {
			continue
		}
		seen[item] = struct{}{}
		result = append(result, item)
	}
	return result
}

func normalizeResendDomain(value string) string {
	text := strings.TrimSpace(strings.ToLower(value))
	if at := strings.LastIndex(text, "@"); at >= 0 {
		text = strings.TrimSpace(text[at+1:])
	}
	return text
}
