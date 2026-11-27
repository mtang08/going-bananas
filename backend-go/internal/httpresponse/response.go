// Package httpresponse writes the versioned local API envelope.
package httpresponse

import (
	"encoding/json"
	"github.com/mtang08/going-bananas/backend-go/api"
	"net/http"
)

func reply(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func Error(w http.ResponseWriter, status int, code, message string, fields []api.ValidationField) {
	if fields == nil {
		fields = []api.ValidationField{}
	}
	reply(w, status, api.ErrorEnvelope{Error: api.ErrorDetail{Code: code, Message: message, RequestId: w.Header().Get("X-Request-ID"), Retryable: status >= 500, Fields: fields}})
}

func Success(w http.ResponseWriter, mode string, revision int, data any) {
	reply(w, 200, map[string]any{"schema_version": "v1", "mode": mode, "data_revision": revision, "data": data})
}
