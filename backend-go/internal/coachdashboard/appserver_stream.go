package coachdashboard

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
)

type replyItem struct {
	phase     string
	streamed  strings.Builder
	completed bool
}

type replyStream struct {
	items   map[string]*replyItem
	final   []string
	size    int
	started bool
	delta   func(string) error
}

func (s *replyStream) item(id string) (*replyItem, error) {
	if id == "" {
		return nil, errors.New("missing item ID")
	}
	v := s.items[id]
	if v == nil {
		if len(s.items) >= 2048 {
			return nil, errors.New("too many app-server items")
		}
		v = &replyItem{}
		s.items[id] = v
	}
	return v, nil
}

func (s *replyStream) emit(i *replyItem, text string) error {
	if text == "" {
		return nil
	}
	s.size += len(text)
	if s.size > 2*maxFrame {
		return errors.New("app-server reply too long")
	}
	delimiter := ""
	if s.started && i.streamed.Len() == 0 {
		delimiter = "\n\n"
	}
	i.streamed.WriteString(text)
	s.started = true
	return s.delta(delimiter + text)
}

func (s *replyStream) handle(item Object, completed bool) error {
	switch field(item, "type") {
	case "commandExecution", "fileChange", "webSearch", "mcpToolCall", "collabAgentToolCall":
		return profileProblem
	case "agentMessage":
	default:
		return nil
	}
	i, err := s.item(idOf(item))
	if err != nil {
		return err
	}
	if !completed {
		i.phase = field(item, "phase")
		return nil
	}
	if i.completed || field(item, "phase") == "commentary" {
		return nil
	}
	text, ok := item["text"].(string)
	if !ok {
		return errors.New("missing agent message text")
	}
	i.completed = true
	s.size += len(text)
	if s.size > 2*maxFrame {
		return errors.New("app-server reply too long")
	}
	s.final = append(s.final, text)
	if rest, ok := strings.CutPrefix(text, i.streamed.String()); ok {
		return s.emit(i, rest)
	}
	return nil
}

func (s *StdioAppServer) toolReply(ctx context.Context, r *RPC, id any, d Object, turnID string, names map[string]bool) error {
	name := field(d, "tool")
	args := object(d["arguments"])
	success := allowedTool(name) && names[name] && field(d, "namespace") == namespace && args != nil
	result := Object{"error": "This coaching tool is unavailable."}
	if success {
		if err := ctx.Err(); err != nil {
			return err
		}
		var err error
		result, err = s.Tools.Call(ctx, turnID, name, args)
		if err != nil {
			return err
		}
	}
	data, err := json.Marshal(result)
	if err != nil {
		return err
	}
	return r.Send(ctx, Object{"id": id, "result": Object{"success": success, "contentItems": []Object{{"type": "inputText", "text": string(data)}}}})
}

func (s *StdioAppServer) stream(ctx context.Context, r *RPC, req TurnRequest, a turnIdentity, names map[string]bool) (string, error) {
	reply := replyStream{items: map[string]*replyItem{}, delta: req.OnDelta}
	for {
		e, err := r.Event(ctx)
		if err != nil {
			return "", err
		}
		d := object(e["params"])
		method := field(e, "method")
		if id, ok := e["id"]; ok {
			if method == "item/tool/call" && a.matches(d) {
				err = s.toolReply(ctx, r, id, d, req.TurnID, names)
			} else {
				err = reject(ctx, r, e)
			}
			if err != nil {
				return "", err
			}
			continue
		}
		if !a.matches(d) {
			continue
		}
		switch method {
		case "item/started", "item/completed":
			err = reply.handle(object(d["item"]), method == "item/completed")
		case "item/agentMessage/delta":
			i := reply.items[field(d, "itemId")]
			if i != nil && !i.completed && (i.phase == "partial_answer" || i.phase == "final_answer") {
				err = reply.emit(i, field(d, "delta"))
			}
		case "turn/completed":
			return reply.finish(object(d["turn"]))
		}
		if err != nil {
			return "", err
		}
	}
}

func (s *replyStream) finish(turn Object) (string, error) {
	if field(turn, "status") != "completed" {
		return "", turnError(turn)
	}
	for _, item := range array(turn["items"]) {
		if err := s.handle(object(item), true); err != nil {
			return "", err
		}
	}
	text := strings.TrimSpace(strings.Join(s.final, "\n\n"))
	if text == "" {
		return "", &Problem{"turn_failed", "Codex finished without a coaching reply. Try again."}
	}
	return text, nil
}

func turnError(turn Object) *Problem {
	if field(turn, "status") == "interrupted" {
		return &Problem{"interrupted", "The coaching reply was interrupted. Try again."}
	}
	switch field(object(turn["error"]), "codexErrorInfo") {
	case "unauthorized":
		return authProblem
	case "modelNotFound":
		return modelProblem
	case "usageLimitExceeded", "rateLimitExceeded":
		return &Problem{"turn_failed", "The Codex account reached its usage limit. Try again later."}
	default:
		return &Problem{"turn_failed", "Codex could not complete this coaching reply. Try again."}
	}
}
