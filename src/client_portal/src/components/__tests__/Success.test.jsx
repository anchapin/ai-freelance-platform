/**
 * Success.jsx - Polling Cleanup Tests
 * 
 * Tests to verify that session fetch requests are properly
 * cleaned up when the component unmounts.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Success from '../Success';

global.fetch = vi.fn();

describe('Success - Session Fetch Cleanup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetch.mockReset();
    localStorage.clear();
    
    // Mock successful response
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        task_id: 'test-task-1',
        client_email: 'test@example.com',
        client_auth_token: 'token-123'
      })
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('should create AbortController for session fetch', () => {
    const abortControllerSpy = vi.spyOn(window, 'AbortController');
    
    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=test-session']}>
        <Success />
      </BrowserRouter>
    );

    expect(abortControllerSpy).toHaveBeenCalled();
    
    unmount();
    abortControllerSpy.mockRestore();
  });

  it('should abort session fetch on unmount', () => {
    let sessionAbortCalled = false;
    const originalAbort = AbortController.prototype.abort;
    
    AbortController.prototype.abort = function() {
      sessionAbortCalled = true;
      originalAbort.call(this);
    };

    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=test-session']}>
        <Success />
      </BrowserRouter>
    );

    unmount();

    expect(sessionAbortCalled).toBe(true);
    AbortController.prototype.abort = originalAbort;
  });

  it('should pass AbortSignal to session fetch request', async () => {
    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=test-session']}>
        <Success />
      </BrowserRouter>
    );

    await new Promise(resolve => setTimeout(resolve, 100));

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('test-session'),
      expect.objectContaining({
        signal: expect.any(AbortSignal)
      })
    );

    unmount();
  });

  it('should not set state after fetch abort on unmount', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    
    fetch.mockImplementation(
      () => new Promise(resolve => {
        setTimeout(() => {
          resolve({
            ok: true,
            json: async () => ({
              task_id: 'test-task',
              client_email: 'test@example.com',
              client_auth_token: 'token'
            })
          });
        }, 500);
      })
    );

    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=test-session']}>
        <Success />
      </BrowserRouter>
    );

    // Unmount before fetch completes
    unmount();

    await new Promise(resolve => setTimeout(resolve, 100));

    const errorCalls = consoleErrorSpy.mock.calls;
    const stateUpdateWarning = errorCalls.some(
      call => call[0]?.includes?.("Can't perform a React state update on an unmounted component")
    );
    
    expect(stateUpdateWarning).toBe(false);
    
    consoleErrorSpy.mockRestore();
  });

  it('should handle AbortError gracefully without logging', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    
    fetch.mockImplementation(() => {
      return Promise.reject(new DOMException('Aborted', 'AbortError'));
    });

    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=test-session']}>
        <Success />
      </BrowserRouter>
    );

    await new Promise(resolve => setTimeout(resolve, 100));
    unmount();

    const errorCalls = consoleErrorSpy.mock.calls;
    const abortErrorLogged = errorCalls.some(
      call => call[0]?.includes?.('AbortError')
    );

    expect(abortErrorLogged).toBe(false);
    consoleErrorSpy.mockRestore();
  });

  it('should store client auth token in localStorage on success', async () => {
    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=test-session']}>
        <Success />
      </BrowserRouter>
    );

    await new Promise(resolve => setTimeout(resolve, 100));

    const storedToken = localStorage.getItem('client_token_test@example.com');
    expect(storedToken).toBe('token-123');

    unmount();
  });

  it('should not store token if email is missing', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        task_id: 'test-task-1',
        // No client_email
        client_auth_token: 'token-123'
      })
    });

    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=test-session']}>
        <Success />
      </BrowserRouter>
    );

    await new Promise(resolve => setTimeout(resolve, 100));

    // No token should be stored
    expect(Object.keys(localStorage)).toHaveLength(0);

    unmount();
  });

  it('should handle 404 session not found error', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 404
    });

    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=invalid-session']}>
        <Success />
      </BrowserRouter>
    );

    await new Promise(resolve => setTimeout(resolve, 100));

    // Should show error state, not crash
    expect(fetch).toHaveBeenCalled();

    unmount();
  });

  it('should handle missing session_id parameter', async () => {
    const { unmount } = render(
      <BrowserRouter initialEntries={['/success']}>
        <Success />
      </BrowserRouter>
    );

    await new Promise(resolve => setTimeout(resolve, 100));

    // Should not make fetch request if session_id is missing
    expect(fetch).not.toHaveBeenCalled();

    unmount();
  });

  it('should not have memory leaks from multiple mount/unmount cycles', async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        task_id: 'test-task',
        client_email: 'test@example.com',
        client_auth_token: 'token'
      })
    });

    const mountUnmountCycles = 5;
    
    for (let i = 0; i < mountUnmountCycles; i++) {
      const { unmount } = render(
        <BrowserRouter initialEntries={[`/success?session_id=session-${i}`]}>
          <Success />
        </BrowserRouter>
      );

      await new Promise(resolve => setTimeout(resolve, 50));
      unmount();
      
      await new Promise(resolve => setTimeout(resolve, 50));
    }

    // Should have created one fetch per cycle
    expect(fetch).toHaveBeenCalledTimes(mountUnmountCycles);
  });

  it('should immediately abort when component unmounts during fetch', async () => {
    let abortCalled = false;
    const originalAbort = AbortController.prototype.abort;
    
    fetch.mockImplementation(() => {
      return new Promise((resolve) => {
        // Simulate slow response
        const timeout = setTimeout(() => {
          resolve({
            ok: true,
            json: async () => ({
              task_id: 'test-task',
              client_email: 'test@example.com',
              client_auth_token: 'token'
            })
          });
        }, 1000);
        
        // Cleanup timeout if aborted
        const original = AbortController.prototype.abort;
        AbortController.prototype.abort = function() {
          abortCalled = true;
          clearTimeout(timeout);
          original.call(this);
        };
      });
    });

    const { unmount } = render(
      <BrowserRouter initialEntries={['/success?session_id=test-session']}>
        <Success />
      </BrowserRouter>
    );

    // Unmount immediately
    unmount();

    expect(abortCalled).toBe(true);
    AbortController.prototype.abort = originalAbort;
  });
});
