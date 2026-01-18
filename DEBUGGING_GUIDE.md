# 🐛 Debugging Guide - Data Not Loading

## Issue
- Previous chats not showing
- File explorer empty
- Deploy button not working

## Root Cause
The refactored code is likely failing during initialization due to:
1. Module import errors (TypeScript can't find the new components/APIs)
2. Monaco Editor blocking initialization
3. API calls failing silently

## ✅ Fixes Applied

### 1. Reordered Initialization
**Before**: Monaco Editor loaded first (could block everything)
**After**: Data loads first, Monaco loads async in background

### 2. Added Comprehensive Logging
Open browser console (F12) and you'll now see:
```
onMount started
Loading settings...
Got settings: [...]
Settings loaded, workspace: /tmp/prometheus_workspace
Loading file tree...
Got items: [...]
Built tree, files count: X
Loading conversations...
Got conversations: X
... etc
```

### 3. Added Error Handling
All async functions now catch and log errors instead of silently failing.

## 🔍 How to Debug

### Step 1: Open Browser Console
1. Press **F12** (or Cmd+Option+I on Mac)
2. Click the **Console** tab
3. Refresh the page (Ctrl+R or Cmd+R)

### Step 2: Check for Errors
Look for **red error messages** like:
```
❌ Cannot find module '$lib/stores'
❌ Failed to fetch
❌ TypeError: ...
```

### Step 3: Check Logs
You should see logs in this order:
```
✅ onMount started
✅ Loading settings...
✅ Got settings: {...}
✅ Loading file tree...
✅ Got items: [array]
✅ Built tree, files count: 5
✅ Loading conversations...
✅ Got conversations: 2
✅ All data loaded!
```

### Step 4: Identify the Problem

#### If you see: `Cannot find module '$lib/...'`
**Problem**: TypeScript/Vite can't find the refactored modules
**Solution**: 
```bash
cd frontend
rm -rf node_modules .svelte-kit
npm install
npm run dev
```

#### If you see: `Failed to fetch` or `NetworkError`
**Problem**: Backend not running or CORS issue
**Solution**: Check that backend is running on http://localhost:8000

#### If you see: `Got items: []` (empty array)
**Problem**: Backend returns empty, workspace path might be wrong
**Solution**: Check workspace path in settings, make sure it exists

#### If logs stop at "Loading X..."
**Problem**: That specific API call is hanging or failing
**Solution**: Check backend logs, that endpoint might be broken

#### If you see: `Editor element not found`
**Problem**: Monaco trying to initialize before DOM ready
**Solution**: Already fixed - it now skips gracefully

## 🚀 Quick Fix Checklist

### Backend Running?
```bash
docker compose logs backend --tail 20
```
Should see: `INFO: Application startup complete`

### Frontend Building?
```bash
cd frontend
npm run dev
```
Should see: `Local: http://localhost:3000/`

### Browser Console Clear?
- Open DevTools (F12)
- Check Console tab
- Should see no red errors
- Should see all the "Loading..." logs

### Data Showing?
- **File Explorer**: Should show files from `/tmp/prometheus_workspace`
- **Chat History**: Should show in History tab (if any exist)
- **Settings**: Click settings icon, should show workspace path

## 🔧 Nuclear Option (If Nothing Works)

```bash
# Stop everything
docker compose down

# Clean frontend
cd frontend
rm -rf node_modules .svelte-kit dist
npm install

# Restart
cd ..
docker compose up --build
```

Then:
1. Open http://localhost:3000
2. Open browser console (F12)
3. Watch the logs
4. Share any errors you see

## 📊 Expected Console Output

```
onMount started
Loading settings...
Got settings: Object { workspacePath: "/tmp/prometheus_workspace", ... }
Settings loaded, workspace: /tmp/prometheus_workspace
Loading file tree...
Fetching file tree...
Got items: Array(5) [ {…}, {…}, {…}, {…}, {…} ]
Built tree, files count: 5
Loading conversations...
Got conversations: 0
Loading rules...
Loaded rules - global: 0 project: 0
Loading memories...
Loaded memories: 0
Loading git status...
Checking GitHub auth...
Loading MCP servers...
Loaded MCP servers: 0
Loading available tools...
Loaded tools: 7
All data loaded!
Initializing Monaco Editor...
Monaco Editor initialized
```

## 💡 What Changed in Refactor

### Before (Working)
- Everything in one file
- Direct variable access
- Inline API calls

### After (Refactored)
- Components in separate files
- Store-based state ($variables)
- API calls in separate modules
- **Imports must resolve correctly**

### Why It Might Break
If Vite/SvelteKit can't find the new files:
- `$lib/stores` → Module not found
- `$lib/api/chat` → Module not found
- Components don't load
- Page stays blank or partially broken

### The Fix
Make sure all imports resolve. Check **Network** tab in DevTools:
- All `.js` files should load (status 200)
- No 404 errors
- No `ERR_MODULE_NOT_FOUND`

---

**Share your browser console output and we'll fix it!** 🚀
