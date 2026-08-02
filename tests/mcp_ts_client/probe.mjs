// Drive the iaiops MCP server from the TYPESCRIPT SDK and print what a
// non-Python client sees. Every other MCP test in this repo uses the Python SDK
// on both ends, so a misreading inside that one library would satisfy both
// halves — this is the second implementation that removes the assumption.
//
// Usage: node probe.mjs   (env: IAIOPS_MCP, IAIOPS_HOME, and the tool to call)
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transport = new StdioClientTransport({
  command: process.env.IAIOPS_PYTHON ?? "python",
  args: ["-c", "from mcp_server.server import main; main()"],
  env: { ...process.env },
});

const client = new Client({ name: "iaiops-ts-probe", version: "0.0.0" }, { capabilities: {} });
await client.connect(transport);

const { tools } = await client.listTools();
const wanted = process.env.IAIOPS_PROBE_TOOL ?? "modbus_read_holding";
const tool = tools.find((t) => t.name === wanted);

const called = await client.callTool({
  name: wanted,
  arguments: { endpoint: "nope", address: 0, count: 1 },
});

console.log(
  JSON.stringify({
    serverInfo: client.getServerVersion(),
    toolCount: tools.length,
    // Annotations are the promise this server makes to a CLIENT — the whole
    // reason a second implementation matters is that it reads them off the wire
    // with its own parser, not ours.
    probedTool: tool && {
      name: tool.name,
      hasDescription: Boolean(tool.description),
      annotations: tool.annotations ?? null,
      inputSchemaType: tool.inputSchema?.type ?? null,
    },
    // A connector failure must arrive as readable CONTENT, not a protocol error
    // that kills the session.
    call: {
      isError: called.isError ?? false,
      text: (called.content ?? []).map((c) => c.text ?? "").join(" ").slice(0, 300),
    },
    // The session survives that failure.
    toolCountAfter: (await client.listTools()).tools.length,
  }),
);

await client.close();
