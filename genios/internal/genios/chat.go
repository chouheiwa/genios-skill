package genios

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
)

type ChatClient struct {
	Base, Key, User string
	HTTP            *http.Client
}

func NewChatClient() (*ChatClient, error) {
	key := strings.TrimSpace(os.Getenv("GENIOS_API_KEY"))
	if key == "" {
		p := os.Getenv("GENIOS_KEY_FILE")
		if p == "" {
			return nil, fmt.Errorf("缺少 GENIOS_API_KEY 或 GENIOS_KEY_FILE")
		}
		b, e := os.ReadFile(p)
		if e != nil {
			return nil, e
		}
		for _, l := range strings.Split(string(b), "\n") {
			l = strings.TrimSpace(l)
			if l != "" && !strings.HasPrefix(l, "#") {
				key = l
				break
			}
		}
	}
	if key == "" {
		return nil, fmt.Errorf("API Key 文件为空")
	}
	return &ChatClient{Base: strings.TrimRight(env("GENIOS_BASE", "https://coze.nankai.edu.cn/api/proxy/api/v1"), "/"), Key: key, User: env("GENIOS_USER", "dev-test"), HTTP: &http.Client{}}, nil
}
func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}
func (c *ChatClient) Post(path string, body map[string]any, stream bool) (*http.Response, error) {
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", c.Base+"/"+path, bytes.NewReader(b))
	req.Header.Set("Apikey", c.Key)
	req.Header.Set("Content-Type", "application/json")
	if stream {
		req.Header.Set("Accept", "text/event-stream")
	}
	r, e := c.HTTP.Do(req)
	if e != nil {
		return nil, e
	}
	if r.StatusCode >= 400 {
		defer r.Body.Close()
		x, _ := io.ReadAll(io.LimitReader(r.Body, 1000))
		return nil, fmt.Errorf("HTTP %d: %s", r.StatusCode, x)
	}
	return r, nil
}
func (c *ChatClient) Conversation() (string, error) {
	r, e := c.Post("create_conversation", map[string]any{"UserID": c.User}, false)
	if e != nil {
		return "", e
	}
	defer r.Body.Close()
	var x struct {
		Conversation struct {
			ID string `json:"AppConversationID"`
		} `json:"Conversation"`
	}
	e = json.NewDecoder(r.Body).Decode(&x)
	return x.Conversation.ID, e
}
func (c *ChatClient) Stream(query, conv string) error {
	if conv == "" {
		var e error
		conv, e = c.Conversation()
		if e != nil {
			return e
		}
	}
	r, e := c.Post("chat_query_v2", map[string]any{"AppConversationID": conv, "Query": query, "UserID": c.User, "ResponseMode": "streaming"}, true)
	if e != nil {
		return e
	}
	defer r.Body.Close()
	s := bufio.NewScanner(r.Body)
	for s.Scan() {
		line := strings.TrimSpace(s.Text())
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		var v map[string]any
		if json.Unmarshal([]byte(strings.TrimSpace(strings.TrimPrefix(line, "data:"))), &v) == nil {
			if x, ok := v["answer"].(string); ok {
				fmt.Print(x)
			}
		}
	}
	fmt.Println()
	return s.Err()
}

func (c *ChatClient) Block(query, conv string) (map[string]any, error) {
	if conv == "" {
		var e error
		conv, e = c.Conversation()
		if e != nil {
			return nil, e
		}
	}
	r, e := c.Post("chat_query_v2", map[string]any{"AppConversationID": conv, "Query": query, "UserID": c.User, "ResponseMode": "blocking"}, false)
	if e != nil {
		return nil, e
	}
	defer r.Body.Close()
	var out map[string]any
	e = json.NewDecoder(r.Body).Decode(&out)
	return out, e
}
