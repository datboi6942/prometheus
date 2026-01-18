# Frontend Refactoring Plan

## Current State
- **Single file**: `+page.svelte` with **3,196 lines**
- Everything in one component: state, logic, UI
- Hard to maintain, test, and reason about

## Target Architecture

```
frontend/src/
├── lib/
│   ├── stores.ts                    # ✅ DONE - Centralized state management
│   ├── api/
│   │   ├── chat.ts                  # Chat API calls
│   │   ├── files.ts                 # File operations API
│   │   ├── git.ts                   # Git operations API
│   │   ├── settings.ts              # Settings API
│   │   ├── conversations.ts         # Conversations API
│   │   └── mcp.ts                   # MCP servers API
│   ├── components/
│   │   ├── panels/
│   │   │   ├── SettingsPanel.svelte       # ✅ DONE - Settings & API keys (~200 lines)
│   │   │   ├── RulesPanel.svelte          # Rules management (~150 lines)
│   │   │   ├── MemoriesPanel.svelte       # Memory bank (~120 lines)
│   │   │   ├── MCPServersPanel.svelte     # MCP server config (~200 lines)
│   │   │   └── GitPanel.svelte            # Git operations (~250 lines)
│   │   ├── explorer/
│   │   │   ├── FileExplorer.svelte        # File tree navigation (~300 lines)
│   │   │   ├── FileContextMenu.svelte     # Right-click menu (~80 lines)
│   │   │   ├── SearchPanel.svelte         # File search (~150 lines)
│   │   │   └── HistoryPanel.svelte        # Chat history (~120 lines)
│   │   ├── chat/
│   │   │   ├── ChatInterface.svelte       # Main chat UI (~400 lines)
│   │   │   ├── ChatMessage.svelte         # Single message component (~150 lines)
│   │   │   ├── ChatInput.svelte           # Input box with controls (~100 lines)
│   │   │   ├── CodeBlock.svelte           # Code display with animation (~120 lines)
│   │   │   └── ToolExecution.svelte       # Tool execution display (~100 lines)
│   │   ├── editor/
│   │   │   ├── CodeEditor.svelte          # Monaco editor wrapper (~200 lines)
│   │   │   └── EditorToolbar.svelte       # Save/close buttons (~60 lines)
│   │   ├── sidebar/
│   │   │   ├── ActivityBar.svelte         # Left icon bar (~80 lines)
│   │   │   └── TopBar.svelte              # Header with settings (~100 lines)
│   │   └── terminal/
│   │       └── Terminal.svelte            # Xterm.js wrapper (~150 lines)
│   └── utils/
│       ├── codeAnimation.ts         # Code writing animation logic
│       ├── fileTree.ts              # File tree building utilities
│       └── monaco.ts                # Monaco editor utilities
└── routes/
    └── +page.svelte                  # Main layout orchestrator (~200 lines)
```

## Refactoring Steps

### Phase 1: Infrastructure (DONE ✅)
- [x] Create shared stores
- [x] Create component directories
- [x] Extract SettingsPanel component

### Phase 2: API Layer (High Priority)
Create dedicated API modules to centralize backend calls:

```typescript
// lib/api/chat.ts
export async function sendChatMessage(...)
export async function streamChat(...)

// lib/api/settings.ts
export async function loadSettings()
export async function saveSetting(key, value)

// lib/api/files.ts
export async function listFiles(path)
export async function readFile(path)
export async function writeFile(path, content)
```

### Phase 3: Panel Components (Medium Priority)
Extract all modal/panel components:
- RulesPanel
- MemoriesPanel
- MCPServersPanel  
- GitPanel

### Phase 4: Explorer Components (Medium Priority)
Break down file explorer:
- FileExplorer (tree view)
- FileContextMenu
- SearchPanel
- HistoryPanel

### Phase 5: Chat Components (High Priority)
Most complex section - needs careful extraction:
- ChatInterface (orchestrator)
- ChatMessage (individual message)
- ChatInput (input controls)
- CodeBlock (with animation)
- ToolExecution (tool results display)

### Phase 6: Editor & Utilities (Low Priority)
- CodeEditor component
- EditorToolbar
- Terminal component

### Phase 7: Main Page Cleanup (Final)
Reduce `+page.svelte` to a simple layout orchestrator that:
- Imports all components
- Handles routing
- Sets up initial state
- ~200 lines max

## Benefits of Refactoring

### 1. **Maintainability**
- Each component has single responsibility
- Easy to find and fix bugs
- Clear code ownership

### 2. **Reusability**
- Components can be used in multiple places
- Easier to build new features
- Less code duplication

### 3. **Testability**
- Each component can be tested in isolation
- Mock stores for unit tests
- Integration tests are clearer

### 4. **Performance**
- Only re-render changed components
- Smaller component trees
- Faster HMR (Hot Module Replacement)

### 5. **Developer Experience**
- Easier onboarding for new developers
- Clear file structure
- Better IDE performance

### 6. **Collaboration**
- Multiple developers can work on different components
- Fewer merge conflicts
- Clearer code reviews

## Implementation Strategy

### Option A: Incremental (Recommended)
1. Create component
2. Test it works
3. Integrate into main page
4. Remove old code
5. Repeat

**Pros**: Safe, reversible, testable at each step  
**Cons**: Takes longer, temporary duplication

### Option B: Big Bang
1. Extract all components at once
2. Wire everything together
3. Fix all issues

**Pros**: Faster completion  
**Cons**: Risky, hard to debug, could break app

### Recommended: **Option A** with these priorities:

1. **Week 1**: API layer + Settings/Rules panels
2. **Week 2**: Chat components (most used)
3. **Week 3**: Explorer components
4. **Week 4**: Editor, Git, cleanup

## Code Examples

### Before (Current)
```svelte
<!-- +page.svelte - 3196 lines -->
<script>
  let showSettings = false;
  let workspacePath = '...';
  let apiKeys = {...};
  // ... 500 more variables
  
  function loadSettings() {...}
  function saveSetting() {...}
  function sendMessage() {...}
  function loadFiles() {...}
  // ... 100 more functions
</script>

<!-- 2000 lines of HTML -->
```

### After (Target)
```svelte
<!-- +page.svelte - 200 lines -->
<script>
  import SettingsPanel from '$lib/components/panels/SettingsPanel.svelte';
  import ChatInterface from '$lib/components/chat/ChatInterface.svelte';
  import FileExplorer from '$lib/components/explorer/FileExplorer.svelte';
  // ... other imports
</script>

<div class="app-layout">
  <ActivityBar />
  <FileExplorer />
  <ChatInterface />
  <SettingsPanel />
</div>
```

```svelte
<!-- SettingsPanel.svelte - 200 lines -->
<script>
  import { showSettings, workspacePath, apiKeys } from '$lib/stores';
  import { saveSetting } from '$lib/api/settings';
  
  // Only settings-related logic here
</script>

<!-- Only settings UI here -->
```

## Migration Checklist

For each component extraction:

- [ ] Identify component boundaries
- [ ] Create new component file
- [ ] Import necessary stores
- [ ] Move HTML template
- [ ] Move related logic
- [ ] Import into main page
- [ ] Test functionality
- [ ] Remove old code
- [ ] Update any references
- [ ] Document component props

## Testing Strategy

```typescript
// SettingsPanel.test.ts
import { render } from '@testing-library/svelte';
import SettingsPanel from './SettingsPanel.svelte';

test('shows settings when store is true', () => {
  showSettings.set(true);
  const { getByText } = render(SettingsPanel);
  expect(getByText('Settings & API Keys')).toBeInTheDocument();
});
```

## Next Steps

1. **Continue refactoring** using this plan
2. **Start with API layer** - extract all fetch calls
3. **Extract panels** - they're self-contained
4. **Extract chat components** - most complex
5. **Clean up main page** - final step

## Estimated Effort

- **API Layer**: 4-6 hours
- **Panel Components**: 8-10 hours  
- **Explorer Components**: 6-8 hours
- **Chat Components**: 12-16 hours (most complex)
- **Editor/Terminal**: 4-6 hours
- **Main Page Cleanup**: 2-4 hours
- **Testing & Fixes**: 8-12 hours

**Total**: 44-62 hours (1-2 weeks full-time)

## Current Progress

✅ **Completed**:
- Shared stores created
- SettingsPanel extracted
- Component directory structure

🚧 **In Progress**:
- You are here!

⏳ **Remaining**:
- 9 more components
- API layer
- Main page cleanup

## Resources

- [Svelte Component Best Practices](https://svelte.dev/docs/svelte-components)
- [Svelte Stores Documentation](https://svelte.dev/docs/svelte-store)
- [Component Composition Patterns](https://svelte.dev/tutorial/slots)
