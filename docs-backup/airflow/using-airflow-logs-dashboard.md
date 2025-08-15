# Using the Airflow Task Logs Dashboard

## Overview

The Airflow Task Logs dashboard provides an intuitive interface to view and analyze logs from your Airflow DAG executions. It's designed to make it easy to find the actual output from your tasks.

## Dashboard URL

Access the dashboard at: `https://grafana.<your-domain>/d/airflow-task-logs/airflow-task-logs`

## Dashboard Sections

### 1. 🎯 Task Output Logs (Top Panel)

This is the main panel that shows what your tasks actually print:
- Print statements from Python tasks
- Echo output from Bash operators
- Any stdout output from your task code

**What you'll see here:**
- `Hello World!`
- `Testing multi-line bash output`
- `This is a print statement that should appear in logs`
- Any other output your tasks generate

### 2. 📝 Python Logger Messages

Shows structured log messages from Python's logging module:
- `logger.info("This is an INFO log message from Python task")`
- `logger.warning()` messages
- `logger.error()` messages

### 3. Task Execution Summary

- **Recent Task Executions**: Table showing DAG/Task names, status (✅/❌), duration, and start times
- **Task Executions by DAG**: Graph showing task execution frequency over time

### 4. Debugging & Errors

- **Error Logs**: All ERROR level logs from Airflow
- **All Logs Browser**: Full access to all Airflow logs for deep debugging

## How to Use

### Finding Task Output

1. Select your DAG from the dropdown at the top (e.g., "hello_world")
2. Look at the "Task Output Logs" panel - this shows the actual output from your tasks
3. Use the time range selector to find logs from specific runs

### Example Task Output

When you run the `hello_world` DAG, you should see:

```
Hello World!
Current date: Wed Jun 11 05:37:25 UTC 2025
Pod hostname: hello-world-say-hello-jxulr6sg
Testing multi-line bash output
This should persist in logs even after pod termination
```

### Tips

1. **Task pods are kept running** after completion to allow log collection
2. **Clean up old pods** periodically with:
   ```bash
   kubectl delete pods -n airflow --field-selector=status.phase=Succeeded
   ```

3. **Use the DAG dropdown** to filter logs to specific DAGs

4. **Expand "Advanced Queries"** section at the bottom for example LogQL queries

## Common Issues

### "No data" in Task Output panel

This usually means:
1. No tasks have run recently - trigger a DAG run
2. The DAG filter is set incorrectly - check the dropdown
3. The time range is too narrow - expand it to "Last 1 hour"

### Can't see print statements

Make sure your Python tasks use:
- `print()` statements (these go to stdout)
- `logger.info()` for structured logging
- `PYTHONUNBUFFERED=1` is set (already configured)

## LogQL Query Examples

For advanced users, here are some useful queries:

```logql
# All output from hello_world tasks
{namespace="airflow", pod=~".*-hello-world-.*"} |~ "subprocess.py.*INFO"

# Find specific text in logs
{namespace="airflow"} |= "Testing multi-line"

# Failed tasks only
{namespace="airflow"} |= "TaskInstance Finished" |= "state=failed"
```