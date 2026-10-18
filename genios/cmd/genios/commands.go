package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	g "genios/internal/genios"
	"io"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

func loadSession() (g.Session, error) {
	s, e := g.LoadSession(g.SessionPath())
	if e == nil {
		return s, nil
	}
	cred, ce := g.ReadCredentials(g.CredentialsPath())
	if ce != nil {
		return g.Session{}, fmt.Errorf("%v；未找到可用账号密码。请运行 genios setup 打开本地管理页面，或配置 %s", e, g.CredentialsPath())
	}
	s, e = g.Login(cred.Account, cred.Password)
	if e != nil {
		return g.Session{}, e
	}
	if e = g.WriteSession(s, g.SessionPath()); e != nil {
		return g.Session{}, e
	}
	return s, nil
}
func client() (*g.Client, error) {
	s, e := loadSession()
	if e != nil {
		return nil, e
	}
	ws := g.Workspace()
	if ws == "" {
		return nil, fmt.Errorf("缺少团队空间 ID；请先从 genios-project.md 配置中取 WorkspaceID，并设置 GENIOS_TEAM_WORKSPACE")
	}
	return g.NewClient(s, ws), nil
}
func flow(a []string) {
	if len(a) < 2 {
		fatal("用法：genios flow check|run|reset|add|set|link ...")
	}
	c, e := client()
	if e != nil {
		fatal(e.Error())
	}
	f := g.NewFlow(c, a[1], "")
	switch a[0] {
	case "check":
		r, e := f.Check()
		printResult(r, e)
	case "reset":
		s, en, e := f.Reset()
		if e != nil {
			fatal(e.Error())
		}
		fmt.Printf("start=%s end=%s\n", s, en)
	case "run":
		if len(a) < 3 {
			fatal("flow run FLOW_ID JSON")
		}
		var in map[string]any
		if e = json.Unmarshal([]byte(a[2]), &in); e != nil {
			fatal(e.Error())
		}
		r, e := f.Run(in, 120*time.Second)
		printResult(r, e)
	case "add":
		if len(a) < 6 {
			fatal("flow add FLOW_ID TYPE NAME X Y")
		}
		x, _ := strconv.ParseFloat(a[4], 64)
		y, _ := strconv.ParseFloat(a[5], 64)
		code, e := f.Add(a[2], a[3], x, y)
		if e != nil {
			fatal(e.Error())
		}
		fmt.Println(code)
	case "set":
		if len(a) < 6 {
			fatal("flow set FLOW_ID CODE TYPE JSON_CONFIG")
		}
		var cfg map[string]any
		if e = json.Unmarshal([]byte(a[5]), &cfg); e != nil {
			fatal(e.Error())
		}
		if e = f.Set(a[2], a[3], a[4], cfg, nil); e != nil {
			fatal(e.Error())
		}
	case "link":
		if len(a) < 4 {
			fatal("flow link FLOW_ID FROM TO [PORT]")
		}
		port := ""
		if len(a) > 4 {
			port = a[4]
		}
		if e = f.Link([][3]string{{a[2], a[3], port}}); e != nil {
			fatal(e.Error())
		}
	default:
		fatal("未知 flow 子命令")
	}
}
func qa(a []string) {
	var dataset, file string
	apply := false
	for i := 0; i < len(a); i++ {
		switch a[i] {
		case "--dataset-id":
			i++
			dataset = a[i]
		case "--kb-file":
			i++
			file = a[i]
		case "--apply":
			apply = true
		}
	}
	if dataset == "" || file == "" {
		fatal("用法：genios qa upload --dataset-id ID --kb-file FILE [--apply]")
	}
	b, e := os.ReadFile(file)
	if e != nil {
		fatal(e.Error())
	}
	var doc struct {
		Entries []struct {
			DocumentID string   `json:"document_id"`
			Main       string   `json:"main_question"`
			Similar    []string `json:"similar_questions"`
			Answer     string   `json:"answer"`
		} `json:"entries"`
	}
	if e = json.Unmarshal(b, &doc); e != nil {
		fatal(e.Error())
	}
	var c *g.Client
	present := map[string]bool{}
	if apply {
		c, e = client()
		if e != nil {
			fatal(e.Error())
		}
		page := 1
		for {
			r, e := c.Call("ListQADocuments", map[string]any{"DatasetID": dataset, "PageNumber": page, "PageSize": 50}, "app")
			if e != nil {
				fatal(e.Error())
			}
			items, _ := r["Items"].([]any)
			if len(items) == 0 {
				break
			}
			for _, v := range items {
				m, _ := v.(map[string]any)
				id := strings.SplitN(fmt.Sprint(m["Description"]), " ", 2)[0]
				present[id] = true
			}
			if len(items) < 50 {
				break
			}
			page++
		}
	}
	for _, x := range doc.Entries {
		if present[x.DocumentID] {
			fmt.Println("跳过（已存在）", x.DocumentID)
			continue
		}
		if !apply {
			fmt.Printf("[dry-run] CreateQADocument %s %s\n", x.DocumentID, x.Main)
			continue
		}
		_, e = c.Call("CreateQADocument", map[string]any{"DatasetID": dataset, "Description": x.DocumentID + " official", "Questions": map[string]any{"MainQuestion": x.Main, "SimilarQuestions": x.Similar}, "Answer": x.Answer}, "app")
		if e != nil {
			fatal(e.Error())
		}
		fmt.Println("已写入", x.DocumentID)
	}
	if !apply {
		fmt.Printf("共 %d 条，未发送请求；确认后加 --apply。\n", len(doc.Entries))
	}
}
func debug(a []string) {
	if len(a) < 2 {
		fatal("用法：genios debug APP_ID 查询...")
	}
	c, e := client()
	if e != nil {
		fatal(e.Error())
	}
	app := a[0]
	draft, e := c.Call("GetAppConfigDraft", map[string]any{"AppID": app}, "app")
	if e != nil {
		fatal(e.Error())
	}
	body := map[string]any{"WorkspaceID": c.Workspace, "AppID": app}
	if cf, ok := draft["ChatFlowConfigDraft"].(map[string]any); ok && cf["WorkflowID"] != nil {
		delete(cf, "UpdateTime")
		body["ChatFlowConfig"] = cf
	} else if cfg, ok := draft["AppConfigDraft"].(map[string]any); ok {
		for _, k := range []string{"UpdateTime", "ModelName", "SummaryModelName", "Version", "VersionDescription"} {
			delete(cfg, k)
		}
		body["AgentMode"] = "Single"
		body["AppConfig"] = cfg
	}
	conv := ""
	for _, q := range a[1:] {
		body["Query"] = q
		if conv != "" {
			body["ConversationID"] = conv
		}
		answer, n, events, e := debugRequest(c, body)
		if e != nil {
			fatal(e.Error())
		}
		conv = n
		fmt.Printf("> %s\n%s\n", q, answer)
		_ = events
	}
}
func debugRequest(c *g.Client, body map[string]any) (string, string, []map[string]any, error) {
	b, _ := json.Marshal(body)
	u := strings.TrimRight(c.Base, "/") + "/bypass/app?Version=2023-08-01&Action=ChatQueryDebug"
	req, _ := http.NewRequest("POST", u, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("accept", "text/event-stream")
	req.Header.Set("x-csrf-token", c.Session.CSRF)
	req.Header.Set("x-top-region", "cn-north-1")
	req.Header.Set("WorkspaceID", c.Workspace)
	req.Header.Set("Cookie", c.Session.Cookie)
	r, e := c.HTTP.Do(req)
	if e != nil {
		return "", "", nil, e
	}
	defer r.Body.Close()
	if r.StatusCode >= 400 {
		v, _ := io.ReadAll(r.Body)
		return "", "", nil, fmt.Errorf("HTTP %d: %s", r.StatusCode, v)
	}
	var answer, conv string
	events := []map[string]any{}
	sc := bufio.NewScanner(r.Body)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		for strings.HasPrefix(line, "data:") {
			line = strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		}
		var v map[string]any
		if json.Unmarshal([]byte(line), &v) != nil {
			continue
		}
		events = append(events, v)
		if conv == "" {
			conv = fmt.Sprint(v["conversation_id"])
		}
		if v["event"] == "message" {
			answer += fmt.Sprint(v["answer"])
		}
	}
	return answer, conv, events, sc.Err()
}
func traces(a []string) {
	if len(a) < 1 {
		fatal("用法：genios traces errors|messages ...")
	}
	c, e := client()
	if e != nil {
		fatal(e.Error())
	}
	switch a[0] {
	case "errors":
		limit := 500
		if len(a) > 1 {
			limit, _ = strconv.Atoi(a[1])
		}
		r, e := c.Call("ListTraceSpans", map[string]any{"PageSize": limit, "Sort": []any{map[string]any{"SortBy": "StartTime", "SortOrder": "Desc"}}}, "observe")
		if e != nil {
			fatal(e.Error())
		}
		items, _ := r["Items"].([]any)
		for _, v := range items {
			m, _ := v.(map[string]any)
			st, _ := m["Status"].(map[string]any)
			if st["Code"] == "ERROR" || st["Message"] != nil {
				fmt.Printf("%v %v %v\n", m["StartTime"], m["Name"], st["Message"])
			}
		}
	case "messages":
		if len(a) < 2 {
			fatal("用法：genios traces messages APP_ID [hours] [limit]")
		}
		hours, limit := 12, 30
		if len(a) > 2 {
			hours, _ = strconv.Atoi(a[2])
		}
		if len(a) > 3 {
			limit, _ = strconv.Atoi(a[3])
		}
		end := time.Now().UTC()
		start := end.Add(-time.Duration(hours) * time.Hour)
		body := map[string]any{"AppID": a[1], "ListOpt": map[string]any{"Sort": []any{map[string]any{"SortField": "created_at", "SortOrder": "desc"}}, "PageNumber": 1, "PageSize": limit}, "Filter": map[string]any{"StartTime": start.Format("2006-01-02T15:04:05.000Z"), "EndTime": end.Format("2006-01-02T15:04:05.000Z")}}
		r, e := c.Call("ListAppMessageWithConLog", body, "app")
		if e != nil {
			fatal(e.Error())
		}
		items, _ := r["AppMessageWithConLogList"].([]any)
		for _, v := range items {
			m, _ := v.(map[string]any)
			fmt.Printf("时间=%v 状态=%v 会话=%v 查询=%v\n", m["CreatedAt"], m["MessageStatus"], m["AppConversationID"], m["QueryInfo"])
		}
	default:
		fatal("未知 traces 子命令")
	}
}
func publish(a []string) {
	if len(a) < 1 {
		fatal("用法：genios publish APP_ID [--prompt-file FILE] [--prompt-marker TEXT] [--max-tokens N] [--reasoning auto|enabled|disabled] [--history-rounds N] [--qa-match auto|force] [--qa-similarity N] [--apply]")
	}
	app := a[0]
	apply := false
	chatflow := false
	version := "v1.0.0"
	description := "API 渠道发布"
	var promptFile, marker, reasoning, qaMatch string
	maxTokens, history := 0, 0
	qaSimilarity := -1.0
	for i := 1; i < len(a); i++ {
		switch a[i] {
		case "--apply":
			apply = true
		case "--chatflow":
			chatflow = true
		case "--version":
			i++
			version = a[i]
		case "--description":
			i++
			description = a[i]
		case "--prompt-file":
			i++
			promptFile = a[i]
		case "--prompt-marker":
			i++
			marker = a[i]
		case "--max-tokens":
			i++
			maxTokens, _ = strconv.Atoi(a[i])
		case "--history-rounds":
			i++
			history, _ = strconv.Atoi(a[i])
		case "--reasoning":
			i++
			reasoning = a[i]
		case "--qa-match":
			i++
			qaMatch = a[i]
		case "--qa-similarity":
			i++
			qaSimilarity, _ = strconv.ParseFloat(a[i], 64)
		}
	}
	c, e := client()
	if e != nil {
		fatal(e.Error())
	}
	r, e := c.Call("GetAppConfigDraft", map[string]any{"AppID": app}, "app")
	if e != nil {
		fatal(e.Error())
	}
	if chatflow {
		cf, ok := r["ChatFlowConfigDraft"].(map[string]any)
		if !ok {
			fatal("该智能体没有 ChatFlowConfigDraft")
		}
		delete(cf, "UpdateTime")
		cf["Version"] = version
		cf["VersionDescription"] = description
		b, _ := json.MarshalIndent(cf, "", "  ")
		fmt.Println(string(b))
		if !apply {
			fmt.Println("未发送写请求；确认后加 --apply。")
			return
		}
		p, e := c.Call("PublishAppConfig", map[string]any{"AppID": app, "ChatFlowConfig": cf}, "app")
		if e != nil {
			fatal(e.Error())
		}
		publishChannel(c, app, fmt.Sprint(p["PublishID"]), description)
		return
	}
	cfg, _ := r["AppConfigDraft"].(map[string]any)
	for _, k := range []string{"UpdateTime", "ModelName", "SummaryModelName", "Version", "VersionDescription"} {
		delete(cfg, k)
	}
	if promptFile != "" {
		b, e := os.ReadFile(promptFile)
		if e != nil {
			fatal(e.Error())
		}
		text := strings.TrimSpace(string(b))
		if marker != "" {
			i := strings.Index(text, marker)
			if i < 0 {
				fatal("提示词文档中找不到 marker")
			}
			text = text[i+len(marker):]
			re := regexp.MustCompile("(?s)```text\\n(.*?)\\n```")
			m := re.FindStringSubmatch(text)
			if len(m) < 2 {
				fatal("marker 后没有 text 代码块")
			}
			text = m[1]
		}
		cfg["PrePrompt"] = text
	}
	mc, _ := cfg["ModelConfig"].(map[string]any)
	if mc == nil {
		mc = map[string]any{}
		cfg["ModelConfig"] = mc
	}
	if maxTokens > 0 {
		mc["MaxTokens"] = maxTokens
	}
	if history > 0 {
		mc["RoundsReserved"] = history
	}
	if reasoning != "" {
		mc["ReasoningSwitchType"] = reasoning
		mc["ReasoningMode"] = reasoning != "disabled"
	}
	if qaMatch != "" || qaSimilarity >= 0 {
		qa, _ := cfg["QADatasetConfig"].(map[string]any)
		if qa == nil {
			qa = map[string]any{}
			cfg["QADatasetConfig"] = qa
		}
		if qaMatch != "" {
			qa["MatchType"] = qaMatch
		}
		if qaSimilarity >= 0 {
			qa["Similarity"] = qaSimilarity
		}
	}
	b, _ := json.MarshalIndent(cfg, "", "  ")
	fmt.Println(string(b))
	if !apply {
		fmt.Println("未发送写请求；确认后加 --apply。")
		return
	}
	if _, e = c.Call("SaveAppConfigDraft", map[string]any{"AppID": app, "AgentMode": "Single", "AppConfigDraft": cfg}, "app"); e != nil {
		fatal(e.Error())
	}
	p, e := c.Call("PublishAppConfig", map[string]any{"AppID": app, "AgentMode": "Single", "AppConfig": cfg}, "app")
	if e != nil {
		fatal(e.Error())
	}
	pid := fmt.Sprint(p["PublishID"])
	publishChannel(c, app, pid, description)
}

func publishChannel(c *g.Client, app, pid, description string) {
	keys := map[string][2]string{"api": {"APIPublishConfigDetailAllStatus", "APIPublishConfigData"}, "web": {"WebPublishConfigDetailAllStatus", "WebPublishConfigData"}, "websdk": {"WebSDKPublishConfigDetailAllStatus", "WebSDKPublishConfigData"}, "lark": {"LarkPublishConfigDetailAllStatus", "LarkPublishConfigData"}}
	apiConf := map[string]any{"APIPublishConfigData": map[string]any{"Enabled": true}}
	if _, e := c.Call("SaveAppBuiltinChannelPublishConfigDraft", map[string]any{"AppID": app, "ChannelCode": "api", "BuiltinChannelConfigData": apiConf}, "app"); e != nil {
		fatal(e.Error())
	}
	channels := []any{"api"}
	data := map[string]any{"APIPublishConfigData": map[string]any{"Enabled": true}}
	brief, e := c.Call("ListAppBriefs", map[string]any{"PageNumber": 1, "PageSize": 100}, "app")
	if e == nil {
		if items, ok := brief["Items"].([]any); ok {
			for _, v := range items {
				m, _ := v.(map[string]any)
				if fmt.Sprint(m["ID"]) != app {
					continue
				}
				if pubs, ok := m["PublishedChannels"].([]any); ok {
					for _, pv := range pubs {
						code := fmt.Sprint(pv)
						if code == "api" {
							continue
						}
						key, ok := keys[code]
						if !ok {
							continue
						}
						detail, ee := c.Call("GetAppBuiltinChannelPublishConfig", map[string]any{"AppID": app, "ChannelCode": code}, "app")
						if ee != nil {
							continue
						}
						all, _ := detail["ConfigDetailAllStatus"].(map[string]any)
						st, _ := all[key[0]].(map[string]any)
						draft, _ := st["DraftConfigDetail"].(map[string]any)
						cfg := draft["ConfigData"]
						if cfg != nil {
							channels = append(channels, code)
							data[key[1]] = cfg
						}
					}
				}
			}
		}
	}
	if _, e := c.Call("PublishAppChannel", map[string]any{"AppID": app, "BuiltinChannels": channels, "BuiltinChannelPublishConfigData": data, "Description": description}, "app"); e != nil {
		fatal(e.Error())
	}
	status := "InReview"
	for i := 0; i < 30 && status == "InReview"; i++ {
		time.Sleep(20 * time.Second)
		h, e := c.Call("ListPublishAppChannelHistory", map[string]any{"AppID": app, "PageNumber": 1, "PageSize": 5}, "app")
		if e != nil {
			fatal(e.Error())
		}
		items, _ := h["Items"].([]any)
		for _, v := range items {
			m, _ := v.(map[string]any)
			if fmt.Sprint(m["PublishID"]) == pid {
				if xs, ok := m["ChannelPublishStatusList"].([]any); ok && len(xs) > 0 {
					if z, ok := xs[0].(map[string]any); ok {
						status = fmt.Sprint(z["Status"])
					}
				}
			}
		}
	}
	fmt.Printf("已发布配置 %s；API 渠道状态：%s\n", pid, status)
}
func printResult(r map[string]any, e error) {
	if e != nil {
		fatal(e.Error())
	}
	b, _ := json.MarshalIndent(r, "", "  ")
	fmt.Println(string(b))
}

var _ = regexp.MustCompile
