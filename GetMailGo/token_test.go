package main

import "testing"

func TestResolveMailboxQueryToken(t *testing.T) {
	secret := []byte("test-secret")
	token := "mbx_eyJjcmVhdGVkX2F0IjoxNzEyMzQ1Njc4LjEyMywiZW1haWwiOiJhYmMxMjNAaWxrb3hwcmEucmVzZW5kLmFwcCIsIm5vbmNlIjoiYWJjMTIzeHl6IiwidiI6MX0.by7fTtSw6sxNoHwcXWeA41hcVud9FdGAwTJdl4JaciQ"

	handle, err := resolveMailboxQueryToken(token, secret)
	if err != nil {
		t.Fatalf("resolveMailboxQueryToken returned error: %v", err)
	}

	if handle.Email != "abc123@ilkoxpra.resend.app" {
		t.Fatalf("unexpected email: %s", handle.Email)
	}
	if handle.CreatedAt != 1712345678.123 {
		t.Fatalf("unexpected created_at: %v", handle.CreatedAt)
	}
}

func TestGenerateMailboxQueryTokenWithNonce(t *testing.T) {
	secret := []byte("test-secret")
	token, err := generateMailboxQueryTokenWithNonce("abc123@ilkoxpra.resend.app", 1712345678.123, "abc123xyz", secret)
	if err != nil {
		t.Fatalf("generateMailboxQueryTokenWithNonce returned error: %v", err)
	}

	expected := "mbx_eyJjcmVhdGVkX2F0IjoxNzEyMzQ1Njc4LjEyMywiZW1haWwiOiJhYmMxMjNAaWxrb3hwcmEucmVzZW5kLmFwcCIsIm5vbmNlIjoiYWJjMTIzeHl6IiwidiI6MX0.by7fTtSw6sxNoHwcXWeA41hcVud9FdGAwTJdl4JaciQ"
	if token != expected {
		t.Fatalf("unexpected token:\nwant: %s\ngot:  %s", expected, token)
	}
}
