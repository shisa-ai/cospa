import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

/**
 * Telemetry-only extension for cospa benchmark trials.
 *
 * It registers no tools, commands, prompt snippets, or context hooks. Boundary
 * events are timestamped as they occur so post-hoc analysis can distinguish
 * provider/inference time from tool execution. Full messages/results remain in
 * pi's normal session JSONL; this file intentionally stays compact.
 */
export default function (pi: ExtensionAPI) {
  const outputPath = process.env.COSPA_BEHAVIOR_TRACE_FILE;
  if (!outputPath) return;

  mkdirSync(dirname(outputPath), { recursive: true });
  let sequence = 0;

  function compact(value: unknown, depth = 0): unknown {
    if (value === null || value === undefined || typeof value === "number" || typeof value === "boolean") {
      return value;
    }
    if (typeof value === "string") {
      return value.length <= 4096 ? value : `${value.slice(0, 4095)}…`;
    }
    if (depth >= 4) return "<nested>";
    if (Array.isArray(value)) {
      return value.slice(0, 25).map((item) => compact(item, depth + 1));
    }
    if (typeof value === "object") {
      const out: Record<string, unknown> = {};
      for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
        if (["content", "oldText", "newText"].includes(key) && typeof item === "string") {
          out[key] = { preview: item.slice(0, 240), chars: item.length };
        } else {
          out[key] = compact(item, depth + 1);
        }
      }
      return out;
    }
    return String(value);
  }

  function jsonChars(value: unknown): number {
    try {
      return JSON.stringify(value).length;
    } catch {
      return 0;
    }
  }

  function record(event: string, fields: Record<string, unknown> = {}) {
    const entry = {
      schema_version: 1,
      sequence: sequence++,
      event,
      monotonic_ns: process.hrtime.bigint().toString(),
      wall_time_ms: Date.now(),
      ...fields,
    };
    try {
      appendFileSync(outputPath, `${JSON.stringify(entry)}\n`, "utf8");
    } catch {
      // Telemetry must never alter agent behavior or fail a benchmark trial.
    }
  }

  record("extension_loaded");
  pi.on("session_start", (event) => record("session_start", { reason: event.reason }));
  pi.on("agent_start", () => record("agent_start"));
  pi.on("agent_end", () => record("agent_end"));
  pi.on("agent_settled", () => record("agent_settled"));
  pi.on("turn_start", (event) => record("turn_start", { turn_index: event.turnIndex }));
  pi.on("turn_end", (event) => record("turn_end", { turn_index: event.turnIndex }));

  pi.on("before_provider_request", () => record("provider_request_start"));
  pi.on("after_provider_response", (event) =>
    record("provider_response_headers", { status: event.status }),
  );

  pi.on("message_end", (event) => {
    if (event.message.role !== "assistant") return;
    const message = event.message;
    record("assistant_message_end", {
      stop_reason: message.stopReason,
      response_id: "responseId" in message ? message.responseId : undefined,
      input_tokens: message.usage?.input ?? 0,
      output_tokens: message.usage?.output ?? 0,
      cache_read_tokens: message.usage?.cacheRead ?? 0,
      reasoning_tokens: "reasoning" in (message.usage ?? {}) ? (message.usage as { reasoning?: number }).reasoning ?? 0 : 0,
    });
  });

  pi.on("tool_execution_start", (event) =>
    record("tool_execution_start", {
      tool_call_id: event.toolCallId,
      tool_name: event.toolName,
      arguments: compact(event.args),
    }),
  );
  pi.on("tool_execution_end", (event) =>
    record("tool_execution_end", {
      tool_call_id: event.toolCallId,
      tool_name: event.toolName,
      is_error: event.isError,
      result_chars: jsonChars(event.result),
    }),
  );
  pi.on("session_shutdown", (event) =>
    record("session_shutdown", { reason: event.reason }),
  );
}
