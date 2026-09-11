/**
 * VisionTrack — Main frontend JS
 * WebSocket connection, event dispatch, utility functions
 */

(function () {
  'use strict';

  // ── WebSocket client ───────────────────────────────────────
  let ws = null;
  let reconnectTimer = null;
  let reconnectDelay = 2000;

  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/events`;

    ws = new WebSocket(url);

    ws.onopen = () => {
      setWSStatus(true);
      reconnectDelay = 2000;
      clearTimeout(reconnectTimer);
    };

    ws.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data);
        // Dispatch to any page that listens
        window.dispatchEvent(new CustomEvent('ws-event', { detail: event }));
        // Update live badge on sidebar
        if (event.event_type === 'new_person' || event.event_type === 'new_detection') {
          bumpLiveBadge();
        }
      } catch (e) {
        console.warn('WS parse error:', e);
      }
    };

    ws.onclose = () => {
      setWSStatus(false);
      reconnectTimer = setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 1.5, 30000);
        connectWS();
      }, reconnectDelay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  function setWSStatus(connected) {
    const el = document.getElementById('ws-status');
    const lbl = el?.querySelector('.ws-label');
    if (el) el.className = `ws-status${connected ? ' connected' : ''}`;
    if (lbl) lbl.textContent = connected ? 'Live' : 'Reconnecting…';
  }

  // ── Live badge counter ─────────────────────────────────────
  let liveCount = 0;
  function bumpLiveBadge() {
    liveCount++;
    const badge = document.getElementById('live-badge');
    if (badge) {
      badge.textContent = liveCount > 99 ? '99+' : liveCount;
    }
  }

  // ── API helper ─────────────────────────────────────────────
  window.apiFetch = async function (url, opts = {}) {
    try {
      const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
      });
      if (!resp.ok) {
        const body = await resp.text();
        console.error(`API error ${resp.status}: ${body}`);
        return null;
      }
      return await resp.json();
    } catch (err) {
      console.error('Fetch failed:', err);
      return null;
    }
  };

  // ── DOM helpers ────────────────────────────────────────────
  window.setText = function (id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? '–';
  };

  window.showToast = function (message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  };

  // ── Time formatters ────────────────────────────────────────
  window.formatTime = function (ts) {
    if (!ts) return '–';
    try {
      return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return ts; }
  };

  window.formatUptime = function (seconds) {
    if (!seconds && seconds !== 0) return '–';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  };

  // ── Init ───────────────────────────────────────────────────
  connectWS();

})();
