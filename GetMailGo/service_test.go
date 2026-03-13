package main

import "testing"

func TestExtractVerificationCode(t *testing.T) {
	content := "Your Verification code: 123456"
	if code := extractVerificationCode(content); code != "123456" {
		t.Fatalf("unexpected verification code: %q", code)
	}
}

func TestMessageTargetsMailbox(t *testing.T) {
	message := map[string]any{
		"to": []any{
			map[string]any{"email": "abc123@ilkoxpra.resend.app"},
		},
	}
	if !messageTargetsMailbox(message, "abc123@ilkoxpra.resend.app") {
		t.Fatal("expected mailbox to match recipient")
	}
}

func TestCompactText(t *testing.T) {
	text := compactText("a   b   c", 10)
	if text != "a b c" {
		t.Fatalf("unexpected compact text: %q", text)
	}
}
