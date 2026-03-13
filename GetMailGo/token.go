package main

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
)

type MailboxHandle struct {
	Email      string
	CreatedAt  float64
	QueryToken string
}

type mailboxTokenPayload struct {
	CreatedAt float64 `json:"created_at"`
	Email     string  `json:"email"`
	Nonce     string  `json:"nonce"`
	Version   int     `json:"v"`
}

type ValidationError struct {
	Message string
}

func (e *ValidationError) Error() string {
	return e.Message
}

func generateMailboxQueryToken(email string, createdAt float64, secret []byte) (string, error) {
	nonce, err := randomTokenURLSafe(8)
	if err != nil {
		return "", err
	}
	return generateMailboxQueryTokenWithNonce(email, createdAt, nonce, secret)
}

func generateMailboxQueryTokenWithNonce(email string, createdAt float64, nonce string, secret []byte) (string, error) {
	payload := mailboxTokenPayload{
		CreatedAt: roundToMillis(createdAt),
		Email:     strings.TrimSpace(strings.ToLower(email)),
		Nonce:     strings.TrimSpace(nonce),
		Version:   1,
	}
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	mac := hmac.New(sha256.New, secret)
	mac.Write(payloadBytes)
	signature := mac.Sum(nil)
	return "mbx_" + base64.RawURLEncoding.EncodeToString(payloadBytes) + "." + base64.RawURLEncoding.EncodeToString(signature), nil
}

func resolveMailboxQueryToken(token string, secret []byte) (MailboxHandle, error) {
	text := strings.TrimSpace(token)
	if !strings.HasPrefix(text, "mbx_") {
		return MailboxHandle{}, &ValidationError{Message: "invalid mailbox query token format"}
	}

	parts := strings.SplitN(text[4:], ".", 2)
	if len(parts) != 2 {
		return MailboxHandle{}, &ValidationError{Message: "invalid mailbox query token format"}
	}

	payloadBytes, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return MailboxHandle{}, &ValidationError{Message: "invalid mailbox query token format"}
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return MailboxHandle{}, &ValidationError{Message: "invalid mailbox query token format"}
	}

	mac := hmac.New(sha256.New, secret)
	mac.Write(payloadBytes)
	expected := mac.Sum(nil)
	if !hmac.Equal(signature, expected) {
		return MailboxHandle{}, &ValidationError{Message: "invalid mailbox query token signature"}
	}

	var payload mailboxTokenPayload
	if err := json.Unmarshal(payloadBytes, &payload); err != nil {
		return MailboxHandle{}, &ValidationError{Message: "invalid mailbox query token payload"}
	}

	email := strings.TrimSpace(strings.ToLower(payload.Email))
	if email == "" {
		return MailboxHandle{}, &ValidationError{Message: "invalid mailbox query token payload"}
	}

	return MailboxHandle{
		Email:      email,
		CreatedAt:  payload.CreatedAt,
		QueryToken: text,
	}, nil
}

func randomTokenURLSafe(byteLen int) (string, error) {
	buf := make([]byte, byteLen)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}

func roundToMillis(value float64) float64 {
	return math.Round(value*1000) / 1000
}

func asValidationError(err error) *ValidationError {
	var validationErr *ValidationError
	if errors.As(err, &validationErr) {
		return validationErr
	}
	return nil
}

func wrapValidation(message string, err error) error {
	if err == nil {
		return &ValidationError{Message: message}
	}
	return &ValidationError{Message: fmt.Sprintf("%s: %v", message, err)}
}
