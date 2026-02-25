/**
 * TaskStatus.jsx - Polling Cleanup Tests
 * 
 * Tests to verify that polling intervals and fetch requests are properly
 * cleaned up when components unmount or dependencies change.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import TaskStatus from '../TaskStatus';

// Mock fetch globally
global.fetch = vi.fn();

describe('TaskStatus - Polling Cleanup', () => {
  beforeEach(() => {
    // Clear all mocks before each test
    vi.clearAllMocks();
    fetch.mockReset();
    
    // Mock successful task response
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 'test-task-1',
        status: 'PAID',
        title: 'Test Task',
        domain: 'accounting',
        description: 'Test description'
      })
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('should create AbortController for task polling', () => {
    const abortControllerSpy = vi.spyOn(window, 'AbortController');
    
    const { unmount } = render(
      <BrowserRouter initialEntries={['/task-status?task_id=test-123']}>
        <TaskStatus />
      </BrowserRouter>
    );

    expect(abortControllerSpy).toHaveBeenCalled();
    
    unmount();
    abortControllerSpy.mockRestore();
  });

  it('should abort task polling on unmount', () => {
    let abortCalled = false;
    const originalAbort = AbortController.prototype.abort;
    
    AbortController.prototype.abort = function() {
      abortCalled = true;
      originalAbort.call(this);
    };

    const { unmount } = render(
      <BrowserRouter initialEntries={['/task-status?task_id=test-123']}>
        <TaskStatus />
      </BrowserRouter>
    );

    unmount();

    expect(abortCalled).toBe(true);
    AbortController.prototype.abort = originalAbort;
  });

  it('should pass AbortSignal to fetch requests', async () => {
    const { unmount } = render(
      <BrowserRouter initialEntries={['/task-status?task_id=test-123']}>
        <TaskStatus />
      </BrowserRouter>
    );

    // Wait for initial fetch to be called
    await new Promise(resolve => setTimeout(resolve, 100));

    // Verify fetch was called with signal option
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('test-123'),
      expect.objectContaining({
        signal: expect.any(AbortSignal)
      })
    );

    unmount();
  });

  it('should not set state after fetch abort on unmount', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    
    // Mock fetch to delay completion until after unmount
    fetch.mockImplementation(
      () => new Promise(resolve => {
        setTimeout(() => {
          resolve({
            ok: true,
            json: async () => ({
              id: 'test-task-1',
              status: 'COMPLETED'
            })
          });
        }, 500);
      })
    );

    const { unmount } = render(
      <BrowserRouter initialEntries={['/task-status?task_id=test-123']}>
        <TaskStatus />
      </BrowserRouter>
    );

    // Unmount before fetch completes
    unmount();

    // Wait a bit for any state update attempts
    await new Promise(resolve => setTimeout(resolve, 100));

    // Should not have React state update warnings
    const errorCalls = consoleErrorSpy.mock.calls;
    const stateUpdateWarning = errorCalls.some(
      call => call[0]?.includes?.("Can't perform a React state update on an unmounted component")
    );
    
    expect(stateUpdateWarning).toBe(false);
    
    consoleErrorSpy.mockRestore();
  });

  it('should create new AbortController when taskId changes', () => {
    let abortCallCount = 0;
    const originalAbort = AbortController.prototype.abort;
    
    AbortController.prototype.abort = function() {
      abortCallCount++;
      originalAbort.call(this);
    };

    // Render with initial taskId
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 'task-1', status: 'PAID' })
    });

    const { rerender, unmount } = render(
      <BrowserRouter initialEntries={['/task-status?task_id=task-1']}>
        <TaskStatus />
      </BrowserRouter>
    );

    const initialAbortCount = abortCallCount;

    // Change taskId - should abort old polling and create new one
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 'task-2', status: 'PAID' })
    });

    rerender(
      <BrowserRouter initialEntries={['/task-status?task_id=task-2']}>
        <TaskStatus />
      </BrowserRouter>
    );

    // Should have called abort for the old polling
    expect(abortCallCount).toBeGreaterThan(initialAbortCount);

    unmount();
    AbortController.prototype.abort = originalAbort;
  });

  it('should abort dashboard polling on unmount', () => {
    let dashboardAbortCalled = false;
    const originalAbort = AbortController.prototype.abort;
    
    AbortController.prototype.abort = function() {
      dashboardAbortCalled = true;
      originalAbort.call(this);
    };

    // Render without taskId to show dashboard
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        stats: { total_tasks: 5, completed_tasks: 3, in_progress_tasks: 2, total_spent: 500 },
        discount: { current_tier: 1, discount_percentage: 0.1 },
        tasks: [],
        next_discount: null
      })
    });

    const { unmount } = render(
      <BrowserRouter initialEntries={['/task-status']}>
        <TaskStatus />
      </BrowserRouter>
    );

    unmount();

    expect(dashboardAbortCalled).toBe(true);
    AbortController.prototype.abort = originalAbort;
  });

  it('should handle AbortError gracefully without state updates', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    
    // Mock fetch to reject with AbortError
    fetch.mockImplementation(() => {
      return Promise.reject(new DOMException('Aborted', 'AbortError'));
    });

    const { unmount } = render(
      <BrowserRouter initialEntries={['/task-status?task_id=test-123']}>
        <TaskStatus />
      </BrowserRouter>
    );

    await new Promise(resolve => setTimeout(resolve, 100));
    unmount();

    // AbortError should not be logged
    const errorCalls = consoleErrorSpy.mock.calls;
    const abortErrorLogged = errorCalls.some(
      call => call[0]?.includes?.('AbortError') && 
               !call[0]?.includes?.("Aborted")
    );

    expect(abortErrorLogged).toBe(false);
    consoleErrorSpy.mockRestore();
  });

  it('should not have memory leaks from multiple mount/unmount cycles', async () => {
    const mountUnmountCycles = 5;
    
    for (let i = 0; i < mountUnmountCycles; i++) {
      fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: `task-${i}`,
          status: 'PAID',
          title: `Task ${i}`,
          domain: 'accounting',
          description: `Test ${i}`
        })
      });

      const { unmount } = render(
        <BrowserRouter initialEntries={[`/task-status?task_id=task-${i}`]}>
          <TaskStatus />
        </BrowserRouter>
      );

      unmount();
      
      // Small delay between cycles
      await new Promise(resolve => setTimeout(resolve, 50));
    }

    // Should have created one AbortController per cycle
    // Plus one for initialization = mountUnmountCycles calls
    expect(fetch).toHaveBeenCalledTimes(mountUnmountCycles);
  });
});

describe('TaskStatus - Polling Configuration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetch.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('should stop polling when task reaches terminal state', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 'test-task',
        status: 'COMPLETED',
        title: 'Test',
        domain: 'accounting',
        description: 'Test'
      })
    });

    const { unmount } = render(
      <BrowserRouter initialEntries={['/task-status?task_id=test-task']}>
        <TaskStatus />
      </BrowserRouter>
    );

    await new Promise(resolve => setTimeout(resolve, 100));

    // Should only fetch once (no retry for completed task)
    expect(fetch).toHaveBeenCalledTimes(1);

    unmount();
  });

  it('should handle multiple terminal states correctly', async () => {
    const terminalStates = ['COMPLETED', 'FAILED', 'CANCELLED'];
    
    for (const status of terminalStates) {
      fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: 'test-task',
          status,
          title: 'Test',
          domain: 'accounting',
          description: 'Test'
        })
      });

      const { unmount } = render(
        <BrowserRouter initialEntries={[`/task-status?task_id=test-${status}`]}>
          <TaskStatus />
        </BrowserRouter>
      );

      await new Promise(resolve => setTimeout(resolve, 100));
      unmount();
    }

    // Each status should result in exactly one fetch call (no retry)
    expect(fetch).toHaveBeenCalledTimes(terminalStates.length);
  });
});
