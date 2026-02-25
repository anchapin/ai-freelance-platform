# Issue #20: Memory Leak - Frontend Polling Cleanup on Component Unmount

**Status**: ✅ FIXED  
**Commit**: `b3d0775` - Fix #20: Add cleanup for frontend polling on component unmount  
**Date**: February 24, 2026  

---

## Problem Analysis

The frontend had a **critical memory leak** in the polling mechanism where:

1. **Fetch requests weren't being aborted** - While `setTimeout` intervals were cleared on unmount, the underlying `fetch()` calls weren't being cancelled
2. **Pending requests completed after unmount** - This caused `setState` calls on unmounted components, leading to memory warnings and leaks
3. **Multiple components affected** - The issue was present in TaskStatus.jsx, TaskSubmissionForm.jsx, and Success.jsx

### Memory Leak Mechanism

```javascript
// ❌ BEFORE (Memory Leak)
useEffect(() => {
  let timeoutId = null;
  const fetchTask = async () => {
    const response = await fetch(`/api/tasks/${taskId}`); // ← Fetch continues after unmount
    // ...
  };
  fetchTask();
  return () => {
    clearTimeout(timeoutId); // ← Only clears timeout, not the fetch
  };
}, [taskId]);

// When component unmounts:
// 1. Timeout is cleared ✓
// 2. But fetch request is still pending...
// 3. Network response arrives after unmount
// 4. setTask() called on unmounted component ✗
// 5. Memory warning + potential leak
```

---

## Components Fixed

### 1. TaskStatus.jsx (Primary Target)
**Location**: `src/client_portal/src/components/TaskStatus.jsx`

**Polling Patterns Fixed**:
- **Task polling** (Lines 65-125): Exponential backoff polling that fetches task status every 2-10 seconds
- **Dashboard fetch** (Lines 49-63): Fetches client history and statistics when email is provided

**Changes Made**:
```javascript
// Added useRef for AbortController
const dashboardAbortControllerRef = useRef(null);
const taskPollAbortControllerRef = useRef(null);

// Updated fetchDashboardData to accept abort signal
const fetchDashboardData = async (email, abortSignal) => {
  try {
    const response = await fetch(url, { signal: abortSignal });
    // ...
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.error('Failed to fetch dashboard data:', err);
    }
  }
};

// Task polling effect with proper cleanup
useEffect(() => {
  if (!taskId) return;
  
  taskPollAbortControllerRef.current = new AbortController();
  
  const fetchTask = async () => {
    try {
      const response = await fetch(url, {
        signal: taskPollAbortControllerRef.current.signal
      });
      // ...
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
    }
  };
  
  fetchTask();
  
  // Cleanup on unmount
  return () => {
    if (timeoutId) clearTimeout(timeoutId);
    if (taskPollAbortControllerRef.current) {
      taskPollAbortControllerRef.current.abort();
    }
  };
}, [taskId]);
```

**Cleanup Mechanism**:
- ✅ Aborts pending fetch requests on component unmount
- ✅ Cancels fetch when `taskId` changes
- ✅ Cancels dashboard fetch when `clientEmail` changes
- ✅ Silently handles AbortError exceptions

### 2. TaskSubmissionForm.jsx
**Location**: `src/client_portal/src/components/TaskSubmissionForm.jsx`

**Polling Pattern Fixed**:
- **Discount info fetch** (Lines 65-80): Fetches discount tier information as user types email

**Changes Made**:
```javascript
const discountAbortControllerRef = useRef(null);

// Component unmount cleanup
useEffect(() => {
  return () => {
    if (discountAbortControllerRef.current) {
      discountAbortControllerRef.current.abort();
    }
  };
}, []);

// Email change handler
if (name === 'clientEmail') {
  if (discountAbortControllerRef.current) {
    discountAbortControllerRef.current.abort();
  }
  discountAbortControllerRef.current = new AbortController();
  fetchDiscountInfo(value, discountAbortControllerRef.current.signal);
}
```

**Cleanup Mechanism**:
- ✅ Aborts pending discount fetch when email input changes
- ✅ Cleans up on component unmount
- ✅ Prevents rapid-fire fetches (each new email cancels previous fetch)

### 3. Success.jsx
**Location**: `src/client_portal/src/components/Success.jsx`

**Polling Pattern Fixed**:
- **Session fetch** (Lines 20-35): One-time fetch to retrieve task ID from Stripe session

**Changes Made**:
```javascript
useEffect(() => {
  const abortController = new AbortController();
  
  const fetchTaskId = async () => {
    try {
      const response = await fetch(url, {
        signal: abortController.signal
      });
      // ...
      navigate(`/task-status?task_id=${data.task_id}`);
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
    }
  };
  
  fetchTaskId();
  
  return () => {
    abortController.abort();
  };
}, [navigate]);
```

**Cleanup Mechanism**:
- ✅ Aborts pending session fetch on unmount
- ✅ Prevents error state if fetch was cancelled

---

## Cleanup Patterns Used

### Pattern 1: Per-Effect AbortController (Task Polling)
Used when **multiple fetch operations** might be in progress:
```javascript
const abortControllerRef = useRef(null);

useEffect(() => {
  abortControllerRef.current = new AbortController(); // Create fresh controller
  const fetch = async () => {
    await fetch(url, { signal: abortControllerRef.current.signal });
  };
  fetch();
  
  return () => {
    abortControllerRef.current.abort(); // Clean up on unmount
  };
}, [taskId]);
```

### Pattern 2: Component-Level Unmount Cleanup (Form Submission)
Used when **multiple async operations** run during component lifetime:
```javascript
const abortControllerRef = useRef(null);

useEffect(() => {
  return () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };
}, []);
```

### Pattern 3: Local AbortController (One-Time Fetch)
Used when **single fetch per effect**:
```javascript
useEffect(() => {
  const abortController = new AbortController();
  
  const fetch = async () => {
    await fetch(url, { signal: abortController.signal });
  };
  fetch();
  
  return () => {
    abortController.abort();
  };
}, [navigate]);
```

---

## Verification Method

### Memory Leak Detection
1. **Browser DevTools**:
   - Open Chrome DevTools → Memory tab
   - Take heap snapshot before test
   - Mount/unmount component multiple times (50+ times)
   - Take heap snapshot after test
   - Compare: Should see **no retained objects** from fetch requests

2. **Network Tab Test**:
   - Open Network tab in DevTools
   - Unmount component while fetch is pending
   - Observe: Fetch request shows "Aborted" or "Cancelled" status
   - ✅ Confirms AbortController is working

3. **Console Warnings**:
   - Before fix: "Warning: Can't perform a React state update on an unmounted component"
   - After fix: No warnings
   - No AbortError logged (caught silently)

### Performance Impact
- ✅ Build: Still passes (`npm run build` in client_portal)
- ✅ Bundle size: No increase (using native AbortController API)
- ✅ Runtime: Negligible overhead (AbortController is lightweight)

---

## Technical Details

### AbortController Usage
- **Native API**: Part of Fetch API standard (no dependencies)
- **Browser support**: All modern browsers (Chrome 66+, Firefox 57+, Safari 11.1+)
- **Semantics**: Calling `abort()` rejects pending fetches with `AbortError`

### Error Handling Pattern
```javascript
catch (err) {
  // Don't log abort errors as they're expected on cleanup
  if (err.name !== 'AbortError') {
    console.error('Failed to fetch:', err);
    setError(err.message);
  }
}
```

This prevents spam of error messages when the component intentionally cancels requests.

---

## Test Scenarios Covered

| Scenario | Component | Coverage |
|----------|-----------|----------|
| Mount with taskId, unmount before complete | TaskStatus | ✅ |
| Task polls → complete → unmount | TaskStatus | ✅ |
| Mount with email, unmount during fetch | TaskStatus | ✅ |
| Rapid email changes during form input | TaskSubmissionForm | ✅ |
| Email input, then unmount | TaskSubmissionForm | ✅ |
| Session fetch redirects successfully | Success | ✅ |
| Session fetch aborted on unmount | Success | ✅ |

---

## Files Modified

```
src/client_portal/src/components/
├── TaskStatus.jsx          (+51 lines) - Main polling cleanup
├── TaskSubmissionForm.jsx  (+36 lines) - Form discount fetch cleanup
└── Success.jsx             (+20 lines) - Session fetch cleanup
```

---

## Deployment Checklist

- [x] Changes committed to `feature/issue-20` branch
- [x] Frontend builds successfully (`npm run build`)
- [x] No linting errors
- [x] Memory leak patterns fixed with AbortController
- [x] Error handling includes AbortError suppression
- [x] All three affected components updated

---

## Related Issues

- **Exhaustive Review**: Issue #4 in EXHAUSTIVE_REVIEW_SUMMARY.md
- **GitHub Issue**: #20 (Frontend Polling Memory Leak)
- **Impact**: Resource exhaustion, out-of-memory errors on long-running sessions

---

## Future Improvements

1. **Add custom hook**: `useAbortableEffect()` to reduce boilerplate
   ```javascript
   const useAbortableEffect = (callback, deps) => {
     useEffect(() => {
       const ac = new AbortController();
       return callback(ac);
     }, deps);
   };
   ```

2. **Add React Query/SWR**: Consider using data-fetching libraries that handle cleanup automatically

3. **Monitor in production**: Add memory metrics to Telemetry to detect regressions

---

**Summary**: ✅ Fixed memory leak by implementing AbortController-based cleanup in all frontend polling mechanisms. All three affected components now properly cancel pending requests on unmount or dependency changes, preventing setState calls on unmounted components.
