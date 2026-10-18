package genios

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

const (
	String      = 0
	Integer     = 1
	Boolean     = 2
	Number      = 3
	Object      = 4
	ArrayString = 5
	ArrayObject = 9
)

type Flow struct {
	C     *Client
	ID    string
	AppID string
}

func NewFlow(c *Client, id string, appID string) *Flow                  { return &Flow{C: c, ID: id, AppID: appID} }
func (f *Flow) Call(a string, b map[string]any) (map[string]any, error) { return f.C.Call(a, b, "app") }
func (f *Flow) Nodes() ([]any, error) {
	r, e := f.Call("GetWorkflow", map[string]any{"ID": f.ID})
	if e != nil {
		return nil, e
	}
	x, _ := r["Nodes"].([]any)
	return x, nil
}
func (f *Flow) Reset() (string, string, error) {
	nodes, e := f.Nodes()
	if e != nil {
		return "", "", e
	}
	var start, end string
	for _, raw := range nodes {
		n := raw.(map[string]any)
		typ := fmt.Sprint(n["Type"])
		code := fmt.Sprint(n["Code"])
		if typ == "Start" {
			start = code
		} else if typ == "End" {
			end = code
		} else {
			if _, e = f.Call("DeleteFlowNode", map[string]any{"FlowID": f.ID, "ID": n["ID"]}); e != nil {
				return "", "", e
			}
		}
	}
	return start, end, nil
}
func (f *Flow) Add(typ, name string, x, y float64) (string, error) {
	r, e := f.Call("CreateFlowNode", map[string]any{"FlowID": f.ID, "Type": typ, "Layout": map[string]any{"X": x, "Y": y}, "Name": name})
	if e != nil {
		return "", e
	}
	n := r["Node"].(map[string]any)
	return fmt.Sprint(n["Code"]), nil
}
func (f *Flow) Set(code, name, typ string, config map[string]any, errorConfig map[string]any) error {
	nc := map[string]any{typ + "Node": config}
	b := map[string]any{"ID": code, "FlowID": f.ID, "Name": name, "NodeConfig": nc}
	if errorConfig != nil {
		b["ErrorConfig"] = errorConfig
	}
	_, e := f.Call("UpdateFlowNode", b)
	return e
}
func (f *Flow) Link(pairs [][3]string) error {
	links := make([]any, 0, len(pairs))
	for _, p := range pairs {
		from := map[string]any{"NodeCode": p[0]}
		if p[2] != "" {
			from["PortID"] = p[2]
		}
		links = append(links, map[string]any{"From": from, "To": map[string]any{"NodeCode": p[1]}})
	}
	_, e := f.Call("UpdateFlowNodeLinks", map[string]any{"FlowID": f.ID, "Links": links})
	return e
}
func (f *Flow) Check() (map[string]any, error) {
	a := "CheckWorkflow"
	b := map[string]any{"ID": f.ID}
	if f.AppID != "" {
		a = "CheckChatflow"
		b["AppID"] = f.AppID
	}
	return f.Call(a, b)
}
func (f *Flow) Run(inputs map[string]any, timeout time.Duration) (map[string]any, error) {
	raw, _ := json.Marshal(inputs)
	r, e := f.Call("SubmitWorkflowDebug", map[string]any{"ID": f.ID, "InputData": string(raw)})
	if e != nil {
		return nil, e
	}
	run := fmt.Sprint(r["runId"])
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		time.Sleep(2 * time.Second)
		x, e := f.Call("QueryDebugProcess", map[string]any{"WorkflowId": f.ID, "RunId": run})
		if e != nil {
			return nil, e
		}
		status := fmt.Sprint(x["status"])
		if status != "processing" && status != "running" && status != "" && status != "<nil>" {
			return x, nil
		}
	}
	return map[string]any{"status": "timeout", "runId": run}, nil
}
func Ref(code, path, name string) map[string]any {
	if name == "" {
		name = path
	}
	return map[string]any{"Name": name, "RefType": "node_field", "NodeCode": code, "Path": path}
}
func Literal(v any) map[string]any {
	b, _ := json.Marshal(v)
	return map[string]any{"Name": "Right", "RefType": "value", "JsonValue": string(b)}
}
func StartInputs(params [][3]any) map[string]any {
	a := []any{}
	for _, p := range params {
		a = append(a, map[string]any{"Name": p[0], "Type": String, "Required": p[1], "Desc": p[2]})
	}
	return map[string]any{"InputSchema": a}
}
func LLM(model string, inputs []any, system, user string, maxTokens int, temp float64) map[string]any {
	return map[string]any{"ModelID": model, "Temperature": temp, "TopP": 0.5, "MaxTokens": maxTokens, "Input": inputs, "SystemPrompt": system, "Prompt": user, "OutputFormat": "text", "OutputSchema": []any{map[string]any{"Name": "raw_output", "Type": String}}, "TimeoutSeconds": 120, "Retries": 1, "ModelInteractiveMode": "direct"}
}
func Code(source string, inputs []any, outputs []string) map[string]any {
	schema := []any{}
	for _, n := range outputs {
		schema = append(schema, map[string]any{"Name": n, "Type": String})
	}
	return map[string]any{"Input": inputs, "Language": 1, "Code": source, "TimeoutSeconds": 30, "Retries": 0, "OutputSchema": schema}
}
func End(pairs [][3]string) map[string]any {
	in := []any{}
	for _, p := range pairs {
		in = append(in, Ref(p[1], p[2], p[0]))
	}
	return map[string]any{"OutputType": "Variable", "Input": in}
}

func Condition(branches ...map[string]any) map[string]any {
	return map[string]any{"Conditions": branches}
}
func Merge(groups [][]map[string]any) map[string]any {
	out := []any{}
	schema := []any{}
	for i, refs := range groups {
		n := fmt.Sprintf("Group%d", i+1)
		vars := make([]any, len(refs))
		for j, v := range refs {
			vars[j] = v
		}
		out = append(out, map[string]any{"name": n, "Type": String, "Variables": vars})
		schema = append(schema, map[string]any{"Name": n, "Type": String})
	}
	return map[string]any{"Groups": out, "OutputSchema": schema}
}
func UserVar(name, alias string) map[string]any {
	if alias == "" {
		alias = name
	}
	return map[string]any{"Name": alias, "RefType": "user_variable", "Path": name}
}
func SysVar(name, alias string) map[string]any {
	if alias == "" {
		alias = strings.ToLower(name)
	}
	return map[string]any{"Name": alias, "RefType": "conversation_variable", "Path": name}
}
func Assign(pairs map[string]map[string]any) map[string]any {
	vars := []any{}
	for name, v := range pairs {
		v["Name"] = name
		vars = append(vars, v)
	}
	return map[string]any{"Variables": vars, "OutputSchemas": []any{map[string]any{"Name": "is_successful", "Type": Boolean}}}
}
func Agent(appID string, query map[string]any, history bool) map[string]any {
	query["Name"] = "sys_user_query"
	return map[string]any{"AppID": appID, "Input": []any{query}, "EnableChatHistories": history}
}
func EndContent(pairs [][3]string, template string) map[string]any {
	in := []any{}
	for _, p := range pairs {
		in = append(in, Ref(p[1], p[2], p[0]))
	}
	return map[string]any{"OutputType": "Content", "Template": template, "StreamOutput": true, "Input": in}
}
func ChatflowConfig(workflowID string, userVars [][3]string, rounds int) map[string]any {
	v := []any{}
	for _, x := range userVars {
		v = append(v, map[string]any{"Name": x[0], "Description": x[1], "Scope": x[2]})
	}
	return map[string]any{"WorkflowID": workflowID, "RoundsReserved": rounds, "VariableConfigs": []any{}, "UserVariableConfigs": v}
}
