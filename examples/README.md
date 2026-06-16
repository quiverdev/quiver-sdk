# Quiver SDK Examples

Learn how to build with the Quiver SDK through practical, runnable examples.

## 📁 Plugin, Hook, and Automation Examples

Plugins extend the CLI and SDK with custom capabilities. Install local files, GitHub file URLs, package directories, git repos, and npm packages with `quiver plugin install`:

### [`./plugins/`](./plugins/)

**Plugin module examples** showing how to extend the CLI and SDK with custom capabilities:

- Register custom tools
- Hook into agent lifecycle events
- Export a reusable plugin module for `.quiver/plugins`

Examples include:
- `weather-metrics.ts` - Weather query tool
- `mac-notify.ts` - macOS Notification Center alerts
- `custom-compaction.ts` - Custom context compaction
- `automation-events.ts` - Plugin event emission
- `background-terminal.ts` - Background shell jobs with setup and job logging

```bash
quiver plugin install https://github.com/quiverdev/quiver/blob/main/sdk/examples/plugins/weather-metrics.ts
quiver -i "What's the weather like in Tokyo and Paris?"
```

Plugin setup receives a host logger through the second `setup` argument. Use
`ctx.logger` for setup-time diagnostics and logs emitted during tool calls:

```ts
setup(api, ctx) {
  ctx.logger?.log("my-plugin setup", {
    sessionId: ctx.session?.sessionId,
    workspaceRoot: ctx.workspaceInfo?.rootPath,
  });

  try {
    // Register tools or perform plugin setup work.
  } catch (error) {
    if (ctx.logger?.error) {
      ctx.logger.error("my-plugin setup failed", { error });
    } else {
      ctx.logger?.log("my-plugin setup failed", { error, severity: "error" });
    }
    throw error;
  }
}
```

`ctx.logger` is session-scoped. For detached work that can outlive the session,
such as background processes, persist status to plugin-owned storage or report
completion through the host event channel instead of calling the captured logger
from long-lived callbacks.

### [`./plugins/typescript-lsp/`](./plugins/typescript-lsp)

TypeScript LSP plugin that gives the agent a `goto_definition` tool powered by the TypeScript Language Service API. Resolves through imports, re-exports, and type aliases -- much more precise than text search.

- Register a tool via `createTool()` and `AgentExtension`
- Use the TypeScript Language Service to resolve symbol definitions
- Cache the language service for efficient repeated lookups
- Zero extra dependencies -- resolves `typescript` from the target project

```bash
quiver plugin install https://github.com/quiverdev/quiver/blob/main/sdk/examples/plugins/typescript-lsp/index.ts
quiver -i "Find where createTool is defined"
```

### [`./plugins/agents-squad/`](./plugins/agents-squad)

**Portable subagent plugin** that adds background agent orchestration tools to the CLI and SDK:

- Export a reusable plugin module for `.quiver/plugins`
- Start background subagents from the main session
- Load bundled or custom agent presets and skills
- Log setup, subagent starts, and follow-ups through `ctx.logger`

Includes pre-configured agents:
- **Anvil** - Build and compile
- **Inquisitor** - Investigation and discovery
- **Oracle** - Planning and architecture
- **Phantom** - Stealth and optimization

Skills available:
- API design, code review, debugging, documentation, migration, refactoring, test generation

```bash
quiver plugin install ./examples/plugins/agents-squad
quiver -i "Use subagents to inspect this repository and report back."
```

Once loaded, the agent can call tools like `start_subagent`, `message_subagent`, `get_subagent`, `list_agent_presets`, `list_skills`, and the handoff tools.

## 📁 Cron & hooks Examples

### [`./cron/`](./cron)

**Example file-based and event-driven automation specs** for global `~/.quiver/cron/`:

Recurring jobs for continuous quality:
- **changelog-generator** — Auto-generate CHANGELOG from commits
- **dependency-check** — Weekly security and update audits
- **test-coverage-report** — Daily coverage metrics
- **performance-baseline** — Build time and bundle size tracking
- **type-check-strict** — TypeScript type safety audits
- **code-style-audit** — Linting and formatting checks
- **dead-code-finder** — Identify unused code
- **documentation-check** — API documentation coverage
- **weekly-metrics-summary** — Fun team metrics report 🎉

Event-driven jobs for PR workflows:
- **pr-changelog-check** — Verify CHANGELOG is updated in PRs
- **pr-test-coverage** — Analyze coverage impact of changes

```bash
mkdir -p ~/.quiver/cron
cp examples/cron/changelog-generator.cron.md ~/.quiver/cron/
mkdir -p ~/.quiver/cron/events
cp examples/cron/events/pr-changelog-check.event.md ~/.quiver/cron/events/
```

See [cron/README.md](./cron/README.md) for full descriptions and usage patterns.

### [`./hooks/`](./hooks)

**Lifecycle hooks** written in bash, Python, or TypeScript that intercept agent actions at key points:

- Log all tool calls (PreToolUse) and results (PostToolUse)
- Block destructive operations
- Require review for critical files
- Inject contextual information
- Track lifecycle events (TaskStart, TaskComplete, SessionShutdown)

Hooks live in `.quiver/hooks/` and are named after the event they handle (PreToolUse, PostToolUse, TaskStart, etc.):

```bash
mkdir -p ~/.quiver/hooks

# Bash hook
cp examples/hooks/PreToolUse.sh ~/.quiver/hooks/
chmod +x ~/.quiver/hooks/PreToolUse.sh

# Or Python
cp examples/hooks/PreToolUse.py ~/.quiver/hooks/PreToolUse.py
chmod +x ~/.quiver/hooks/PreToolUse.py

# Or TypeScript (runs via bun)
cp examples/hooks/PreToolUse.ts ~/.quiver/hooks/PreToolUse.ts
chmod +x ~/.quiver/hooks/PreToolUse.ts

quiver -i "do something"  # Hooks will execute automatically
```

## 🚀 Quick Start

To use the SDK in your own Node app (outside this monorepo), start with:

```bash
npm add @quiver/core
```

Add `@quiver/agents` or `@quiver/llms` only if you intentionally want lower-level control. For RPC client helpers, prefer importing from `@quiver/core` when you want the app-facing SDK surface.

Current SDK layering:

- `@quiver/core` owns config discovery/watchers, runtime plugin loading, and the context pipeline
- context compaction is core-owned and runs through turn preparation before model calls
- most app integrations should stay on the `@quiver/core` surface unless they intentionally need lower-level agent or model control

## 📚 Learning Path

**Building plugins?**
- Start with [`./plugins/`](./plugins/) for basic tool and event patterns
- Explore [`./plugins/typescript-lsp/`](./plugins/typescript-lsp) for integration with language services
- See [`./plugins/agents-squad/`](./plugins/agents-squad) for advanced agent orchestration

**Building integrations?**
- Review [`./cron/`](./cron) for automation and event-driven workflows
- Explore [`desktop-app/`](../../apps/examples/desktop-app), [`vscode/`](../../apps/examples/vscode), and [`menubar/`](../../apps/examples/menubar) for app integration patterns

**Controlling agent behavior?**
- Explore [`./hooks/`](./hooks) to intercept and modify tool execution, log actions, or enforce policies

## 📖 Documentation

- [Quiver SDK README](../packages/README.md)
- [Architecture Guide](../ARCHITECTURE.md)
- [Individual Package Docs](../packages/)

## 🛠️ Requirements

- **Node.js 22+** - For package compatibility
- **API Key** - Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or provider-specific key (for SDK examples)
- **Bun** - Optional, install from [bun.sh](https://bun.sh) for running examples
