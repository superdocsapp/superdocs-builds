// Package superdocs — SuperDocs client (Go), the four core calls, mirroring the
// validated Python client. Behaviour is pinned by the shared conformance scenarios.
package superdocs

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

type Client struct {
	BaseURL string
	APIKey  string
	HTTP    *http.Client
}

func New(baseURL, apiKey string) *Client {
	return &Client{BaseURL: strings.TrimRight(baseURL, "/"), APIKey: apiKey, HTTP: http.DefaultClient}
}

func (c *Client) do(method, path string, body any) (*http.Response, error) {
	var buf io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		buf = bytes.NewReader(b)
	}
	req, _ := http.NewRequest(method, c.BaseURL+path, buf)
	req.Header.Set("Authorization", "Bearer "+c.APIKey)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("%d %s", resp.StatusCode, string(b))
	}
	return resp, nil
}

func (c *Client) ChatAsync(message, sessionID, documentHTML, approvalMode string) (map[string]any, error) {
	body := map[string]any{"message": message, "session_id": sessionID, "response_mode": "compact"}
	if documentHTML != "" {
		body["document_html"] = documentHTML
	}
	if approvalMode != "" {
		body["approval_mode"] = approvalMode
	}
	return c.decode(c.do("POST", "/v1/chat/async", body))
}

func (c *Client) GetJob(jobID string) (map[string]any, error) { return c.decode(c.do("GET", "/v1/jobs/"+jobID, nil)) }

// Approve — AMBIGUITIES #3: job_id + change_id (never chunk_id)
func (c *Client) Approve(sessionID, jobID string, changes []map[string]any) (map[string]any, error) {
	return c.decode(c.do("POST", "/v1/chat/"+sessionID+"/approve", map[string]any{"job_id": jobID, "approved": true, "changes": changes}))
}

func (c *Client) Export(sessionID, format string) ([]byte, error) {
	resp, err := c.do("POST", "/v1/documents/export", map[string]any{"session_id": sessionID, "format": format})
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

func (c *Client) decode(resp *http.Response, err error) (map[string]any, error) {
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out map[string]any
	json.NewDecoder(resp.Body).Decode(&out)
	return out, nil
}
