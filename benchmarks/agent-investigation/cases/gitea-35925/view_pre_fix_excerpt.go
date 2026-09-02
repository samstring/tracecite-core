// Source: go-gitea/gitea routers/web/repo/actions/view.go
// Commit: 372d24b84bc6f4c5562792009c6b6e6a4aeb85f8

type ViewResponse struct {
    Logs struct {
        StepsLog []*ViewStepLog `json:"stepsLog"`
    } `json:"logs"`
}

type ViewStepLog struct {
    Step    int                `json:"step"`
    Cursor  int64              `json:"cursor"`
    Lines   []*ViewStepLogLine `json:"lines"`
    Started int64              `json:"started"`
}

type ViewStepLogLine struct {
    Index     int64   `json:"index"`
    Message   string  `json:"message"`
    Timestamp float64 `json:"timestamp"`
}

func ViewPost(ctx *context_module.Context) {
    // ...
    resp := &ViewResponse{}
    // ...
    resp.Logs.StepsLog = make([]*ViewStepLog, 0)
    if task != nil {
        steps, logs, err := convertToViewModel(ctx, req.LogCursors, task)
        if err != nil {
            ctx.ServerError("convertToViewModel", err)
            return
        }
        resp.State.CurrentJob.Steps = append(resp.State.CurrentJob.Steps, steps...)
        resp.Logs.StepsLog = append(resp.Logs.StepsLog, logs...)
    }
    ctx.JSON(http.StatusOK, resp)
}

func convertToViewModel(ctx *context_module.Context, cursors []LogCursor, task *actions_model.ActionTask) ([]*ViewJobStep, []*ViewStepLog, error) {
    var logs []*ViewStepLog
    steps := actions.FullSteps(task)
    for _, cursor := range cursors {
        if !cursor.Expanded {
            continue
        }
        step := steps[cursor.Step]
        logLines := make([]*ViewStepLogLine, 0)
        index := step.LogIndex + cursor.Cursor
        validCursor := cursor.Cursor >= 0 && cursor.Cursor < step.LogLength && index < int64(len(task.LogIndexes))
        if validCursor {
            length := step.LogLength - cursor.Cursor
            offset := task.LogIndexes[index]
            logRows, err := actions.ReadLogs(ctx, task.LogInStorage, task.LogFilename, offset, length)
            if err != nil {
                return nil, nil, fmt.Errorf("actions.ReadLogs: %w", err)
            }
            for i, row := range logRows {
                logLines = append(logLines, &ViewStepLogLine{
                    Index:     cursor.Cursor + int64(i) + 1,
                    Message:   row.Content,
                    Timestamp: float64(row.Time.AsTime().UnixNano()) / float64(time.Second),
                })
            }
        }
        logs = append(logs, &ViewStepLog{
            Step:   cursor.Step,
            Cursor: cursor.Cursor + int64(len(logLines)),
            Lines:  logLines,
        })
    }
    return nil, logs, nil
}
