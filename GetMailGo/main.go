package main

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"io/fs"
	"log"
	"net/http"
	"strconv"
	"strings"
)

//go:embed web/*
var webFiles embed.FS

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatalf("加载配置失败: %v", err)
	}

	secret, source, err := loadTokenSecret(cfg)
	if err != nil {
		log.Fatalf("加载 token secret 失败: %v", err)
	}

	service := NewMailService(cfg, secret, source)
	handler, err := newHTTPHandler(service)
	if err != nil {
		log.Fatalf("初始化 HTTP 服务失败: %v", err)
	}

	address := cfg.Host + ":" + itoa(cfg.Port)
	log.Printf("GetMailGo listening on http://%s", address)
	if err := http.ListenAndServe(address, handler); err != nil {
		log.Fatalf("服务启动失败: %v", err)
	}
}

func newHTTPHandler(service *MailService) (http.Handler, error) {
	subFS, err := fs.Sub(webFiles, "web")
	if err != nil {
		return nil, err
	}

	staticHandler := http.FileServer(http.FS(subFS))
	mux := http.NewServeMux()

	mux.Handle("/static/", http.StripPrefix("/static/", staticHandler))
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		serveEmbeddedFile(w, r, subFS, "index.html", "text/html; charset=utf-8")
	})

	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeDetailError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		writeJSON(w, http.StatusOK, service.HealthSnapshot())
	})

	mux.HandleFunc("/api/mailbox/lookup", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeDetailError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}

		defer r.Body.Close()
		var req MailboxLookupRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeDetailError(w, http.StatusBadRequest, "请求体不是合法 JSON")
			return
		}
		if strings.TrimSpace(req.MailToken) == "" || len(strings.TrimSpace(req.MailToken)) < 8 {
			writeDetailError(w, http.StatusBadRequest, "mail_token 无效: mail_token 不能为空")
			return
		}
		timeout := 15
		if req.Timeout != nil {
			timeout = *req.Timeout
		}
		limit := 10
		if req.Limit != nil {
			limit = *req.Limit
		}

		response, err := service.LookupMailbox(r.Context(), req.MailToken, timeout, limit)
		if err != nil {
			var validationErr *ValidationError
			if errors.As(err, &validationErr) {
				writeDetailError(w, http.StatusBadRequest, "mail_token 无效: "+validationErr.Message)
				return
			}
			if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
				writeDetailError(w, http.StatusRequestTimeout, "请求已取消")
				return
			}
			writeDetailError(w, http.StatusInternalServerError, "邮件查询失败: "+err.Error())
			return
		}
		writeJSON(w, http.StatusOK, response)
	})

	return logMiddleware(mux), nil
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	encoder := json.NewEncoder(w)
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(payload)
}

func writeDetailError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func logMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		log.Printf("%s %s", r.Method, r.URL.Path)
		next.ServeHTTP(w, r)
	})
}

func itoa(value int) string {
	return strconv.Itoa(value)
}

func serveEmbeddedFile(w http.ResponseWriter, r *http.Request, filesystem fs.FS, name string, contentType string) {
	data, err := fs.ReadFile(filesystem, name)
	if err != nil {
		http.NotFound(w, r)
		return
	}

	w.Header().Set("Content-Type", contentType)
	if _, err := w.Write(data); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
	}
}
