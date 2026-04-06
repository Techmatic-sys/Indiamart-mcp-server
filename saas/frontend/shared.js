/**
 * LeadFlow CRM — Shared JavaScript Module v2.0
 * Premium UI: Ripple effects, smooth animations, enhanced toasts,
 * micro-interactions, and visual polish.
 */

const API_BASE = window.location.origin;

// ═══════════════════════════════════════════════════════════════════════════
//  Auth Guard & API
// ═══════════════════════════════════════════════════════════════════════════

function authGuard() {
    const token = localStorage.getItem('token');
    if (!token) { window.location.href = '/app/login'; return false; }
    return true;
}

async function apiCall(method, url, body = null) {
    const token = localStorage.getItem('token');
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (token) opts.headers['Authorization'] = `Bearer ${token}`;
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`${API_BASE}${url}`, opts);
    if (res.status === 401) { localStorage.removeItem('token'); window.location.href = '/app/login'; return; }
    return res;
}

function logout() {
    // Fade out animation before redirect
    document.body.style.transition = 'opacity 0.3s ease';
    document.body.style.opacity = '0';
    setTimeout(() => {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = '/app/login';
    }, 300);
}

// ═══════════════════════════════════════════════════════════════════════════
//  Toast Notifications (Enhanced with slide-in/out + progress bar)
// ═══════════════════════════════════════════════════════════════════════════

function showToast(message, type = 'info') {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = {
        success: 'fa-check-circle',
        error: 'fa-times-circle',
        info: 'fa-info-circle',
        warning: 'fa-exclamation-triangle'
    };

    toast.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i><span>${message}</span>`;
    container.appendChild(toast);

    // Auto-dismiss with exit animation
    const dismissTimeout = setTimeout(() => dismissToast(toast), 3500);

    // Click to dismiss early
    toast.addEventListener('click', () => {
        clearTimeout(dismissTimeout);
        dismissToast(toast);
    });

    // Limit max visible toasts
    const toasts = container.querySelectorAll('.toast');
    if (toasts.length > 5) {
        dismissToast(toasts[0]);
    }
}

function dismissToast(toast) {
    if (!toast || toast.classList.contains('toast-exit')) return;
    toast.classList.add('toast-exit');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
}

// ═══════════════════════════════════════════════════════════════════════════
//  Dark Mode (Enhanced with smooth transition)
// ═══════════════════════════════════════════════════════════════════════════

function initTheme() {
    const saved = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    updateThemeIcon(saved);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';

    // Add transition class for smooth theme change
    document.documentElement.style.transition = 'background 0.4s ease, color 0.4s ease';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeIcon(next);

    // Animate the toggle button icon
    const btn = document.getElementById('themeToggle');
    if (btn) {
        const icon = btn.querySelector('i');
        if (icon) {
            icon.style.transition = 'transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)';
            icon.style.transform = 'rotate(360deg) scale(1.2)';
            setTimeout(() => { icon.style.transform = 'rotate(0) scale(1)'; }, 400);
        }
    }
}

function updateThemeIcon(theme) {
    const btn = document.getElementById('themeToggle');
    if (btn) {
        btn.innerHTML = theme === 'dark'
            ? '<i class="fas fa-sun"></i>'
            : '<i class="fas fa-moon"></i>';
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  Sidebar (with smooth interactions)
// ═══════════════════════════════════════════════════════════════════════════

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    sidebar.classList.toggle('open');
    overlay.classList.toggle('show');

    // Prevent body scroll when sidebar is open on mobile
    if (sidebar.classList.contains('open')) {
        document.body.style.overflow = 'hidden';
    } else {
        document.body.style.overflow = '';
    }
}

function closeSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebarOverlay').classList.remove('show');
    document.body.style.overflow = '';
}

function loadUser() {
    try {
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        const nameEl = document.getElementById('userName');
        const avatarEl = document.getElementById('userAvatar');
        const emailEl = document.getElementById('userEmail');
        if (user.name && nameEl) { nameEl.textContent = user.name; }
        if (user.name && avatarEl) {
            avatarEl.textContent = user.name.charAt(0).toUpperCase();
        }
        if (user.email && emailEl) { emailEl.textContent = user.email; }
    } catch (e) { /* ignore */ }
}

// ═══════════════════════════════════════════════════════════════════════════
//  Notification Center (Enhanced with animations)
// ═══════════════════════════════════════════════════════════════════════════

async function loadNotificationCount() {
    try {
        const res = await apiCall('GET', '/api/notifications?unread_only=true&per_page=1');
        if (!res) return;
        const data = await res.json();
        const badge = document.getElementById('notifBadge');
        if (badge) {
            if (data.unread_count > 0) {
                badge.textContent = data.unread_count > 9 ? '9+' : data.unread_count;
                badge.classList.remove('hidden');
                // Pulse animation on new count
                badge.style.animation = 'none';
                badge.offsetHeight; // force reflow
                badge.style.animation = 'badgePop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)';
            } else {
                badge.classList.add('hidden');
            }
        }
    } catch (e) { /* silent */ }
}

async function toggleNotificationPanel() {
    const panel = document.getElementById('notifPanel');
    const overlay = document.getElementById('notifOverlay');
    if (panel.classList.contains('open')) {
        panel.classList.remove('open');
        overlay.classList.remove('show');
        return;
    }
    panel.classList.add('open');
    overlay.classList.add('show');
    await loadNotifications();
}

function closeNotificationPanel() {
    const panel = document.getElementById('notifPanel');
    const overlay = document.getElementById('notifOverlay');
    if (panel) panel.classList.remove('open');
    if (overlay) overlay.classList.remove('show');
}

async function loadNotifications() {
    const body = document.getElementById('notifBody');
    if (!body) return;

    // Show loading with dots animation
    body.innerHTML = `
        <div style="padding:40px;text-align:center;color:var(--text-muted);">
            <div class="dots-loader">
                <span></span><span></span><span></span>
            </div>
            <div style="margin-top:12px;font-size:12px;">Loading notifications...</div>
        </div>`;

    try {
        const res = await apiCall('GET', '/api/notifications?per_page=20');
        if (!res) return;
        const data = await res.json();
        const notifs = data.notifications || [];

        if (!notifs.length) {
            body.innerHTML = `
                <div class="empty-state" style="padding:60px 20px;">
                    <div class="empty-illustration" style="width:80px;height:80px;font-size:32px;">
                        <i class="fas fa-bell-slash"></i>
                    </div>
                    <p style="font-size:13px;color:var(--text-muted);">No notifications yet</p>
                </div>`;
            return;
        }

        body.innerHTML = notifs.map(n => `
            <div class="notif-item ${n.is_read ? '' : 'unread'}" onclick="markNotifRead('${n.id}', this)">
                <div class="notif-title">${escapeHtml(n.title)}</div>
                <div class="notif-message">${escapeHtml(n.message)}</div>
                <div class="notif-time">${timeAgo(n.created_at)}</div>
            </div>
        `).join('');
    } catch (e) {
        body.innerHTML = `
            <div style="padding:40px 20px;text-align:center;color:var(--text-muted);">
                <i class="fas fa-exclamation-circle" style="font-size:24px;margin-bottom:8px;display:block;opacity:0.5;"></i>
                <span style="font-size:13px;">Failed to load notifications</span>
            </div>`;
    }
}

async function markNotifRead(id, el) {
    if (el) {
        el.classList.remove('unread');
        el.style.transition = 'background 0.3s ease';
    }
    await apiCall('PUT', `/api/notifications/${id}/read`);
    loadNotificationCount();
}

async function markAllNotifsRead() {
    await apiCall('PUT', '/api/notifications/read-all');
    loadNotificationCount();
    loadNotifications();
    showToast('All notifications marked as read', 'success');
}

// ═══════════════════════════════════════════════════════════════════════════
//  Utilities
// ═══════════════════════════════════════════════════════════════════════════

function escapeHtml(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatDateTime(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatCurrency(num) {
    if (num == null) return '₹0';
    return '₹' + Number(num).toLocaleString('en-IN');
}

function timeAgo(dateStr) {
    if (!dateStr) return '';
    const now = new Date();
    const d = new Date(dateStr);
    const diff = Math.floor((now - d) / 1000);
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return formatDate(dateStr);
}

function getScoreBadge(score) {
    if (score >= 70) return '<span class="badge badge-hot">🔥 Hot</span>';
    if (score >= 40) return '<span class="badge badge-warm">🌤 Warm</span>';
    return '<span class="badge badge-cold">❄️ Cold</span>';
}

function getStageBadge(stage) {
    return `<span class="badge-stage ${stage || 'new'}">${stage || 'new'}</span>`;
}

function getTypeBadge(type) {
    if (type === 'W' || type === 'direct' || type === 'Direct') return '<span class="badge badge-direct">Direct</span>';
    return '<span class="badge badge-buylead">Buy Lead</span>';
}

/** Animated counter with easeOutCubic and optional prefix/suffix */
function animateCounter(el, target, duration = 1000) {
    const start = 0;
    const startTime = performance.now();

    // Add a subtle scale animation
    el.style.transition = 'transform 0.3s ease';
    el.style.transform = 'scale(1.02)';
    setTimeout(() => { el.style.transform = 'scale(1)'; }, 300);

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // easeOutExpo for snappier feel
        const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
        const current = Math.round(start + (target - start) * eased);
        el.textContent = current.toLocaleString('en-IN');
        if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
}

/** Generate skeleton loading placeholders with stagger animation */
function renderSkeletons(container, count = 3, type = 'card') {
    let html = '';
    for (let i = 0; i < count; i++) {
        const stagger = `animation-delay: ${i * 0.08}s;`;
        if (type === 'card') {
            html += `<div class="skeleton skeleton-card" style="margin-bottom:14px;${stagger}"></div>`;
        } else if (type === 'stat') {
            html += `<div class="skeleton skeleton-stat" style="${stagger}"></div>`;
        } else if (type === 'row') {
            html += `<tr><td colspan="10"><div class="skeleton skeleton-text" style="width:100%;height:44px;border-radius:8px;${stagger}"></div></td></tr>`;
        }
    }
    container.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════════════════════
//  Ripple Effect (auto-attached to all .btn elements)
// ═══════════════════════════════════════════════════════════════════════════

function createRipple(event) {
    const button = event.currentTarget;
    const rect = button.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 2;

    const ripple = document.createElement('span');
    ripple.className = 'ripple';
    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${event.clientY - rect.top - size / 2}px`;

    // Remove old ripples
    const existing = button.querySelector('.ripple');
    if (existing) existing.remove();

    button.appendChild(ripple);
    ripple.addEventListener('animationend', () => ripple.remove());
}

function initRippleEffects() {
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn');
        if (btn) createRipple(e);
    });
}

// ═══════════════════════════════════════════════════════════════════════════
//  Intersection Observer for Scroll Animations
// ═══════════════════════════════════════════════════════════════════════════

function initScrollAnimations() {
    if (!('IntersectionObserver' in window)) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animate-visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    // Auto-observe elements with data-animate attribute
    document.querySelectorAll('[data-animate]').forEach(el => {
        el.style.opacity = '0';
        observer.observe(el);
    });
}

// ═══════════════════════════════════════════════════════════════════════════
//  Sidebar HTML Generator (Enhanced with active indicator)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Generates the standard LeadFlow sidebar HTML.
 * @param {string} activePage - Current page name: 'dashboard', 'leads', 'pipeline', 'analytics', 'settings', 'billing'
 */
function generateSidebar(activePage) {
    const pages = [
        { group: 'Main', items: [
            { id: 'dashboard', icon: 'fa-th-large', label: 'Dashboard', href: '/app/dashboard' },
            { id: 'leads', icon: 'fa-users', label: 'Leads', href: '/app/leads' },
            { id: 'pipeline', icon: 'fa-columns', label: 'Pipeline', href: '/app/pipeline' },
            { id: 'analytics', icon: 'fa-chart-bar', label: 'Analytics', href: '/app/analytics' },
        ]},
        { group: 'Sales', items: [
            { id: 'catalog', icon: 'fa-boxes', label: 'Product Catalog', href: '/app/catalog' },
            { id: 'quotations', icon: 'fa-file-invoice', label: 'Quotations', href: '/app/quotations' },
        ]},
        { group: 'Tools', items: [
            { id: 'briefing', icon: 'fa-sun', label: 'Morning Briefing', href: '/app/briefing' },
            { id: 'settings', icon: 'fa-cog', label: 'Settings', href: '/app/settings' },
            { id: 'billing', icon: 'fa-credit-card', label: 'Billing', href: '/app/billing' },
        ]},
    ];

    let navHtml = '';
    pages.forEach(group => {
        navHtml += `<div class="nav-label">${group.group}</div>`;
        group.items.forEach(item => {
            const isActive = item.id === activePage ? 'active' : '';
            navHtml += `<a href="${item.href}" class="nav-item ${isActive}"><i class="fas ${item.icon}"></i><span>${item.label}</span></a>`;
        });
    });

    return `
    <div class="sidebar-overlay" id="sidebarOverlay" onclick="closeSidebar()"></div>
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <h2><i class="fas fa-bolt"></i> LeadFlow</h2>
            <div class="brand-sub">AI-Powered CRM</div>
        </div>
        <nav class="sidebar-nav">${navHtml}</nav>
        <div class="sidebar-footer">
            <div class="user-info">
                <div class="user-avatar" id="userAvatar">U</div>
                <div class="user-details">
                    <div class="name" id="userName">User</div>
                    <div class="email" id="userEmail">user@email.com</div>
                </div>
            </div>
            <button class="logout-btn" onclick="logout()"><i class="fas fa-sign-out-alt"></i> Sign Out</button>
        </div>
    </aside>`;
}

/**
 * Generate the standard topbar with theme toggle and notification bell.
 * @param {string} title - Page title
 * @param {string} rightHtml - Optional extra HTML for the right side
 */
function generateTopbar(title, rightHtml = '') {
    return `
    <div class="topbar">
        <div class="topbar-left">
            <button class="menu-toggle" onclick="toggleSidebar()"><i class="fas fa-bars"></i></button>
            <h1>${title}</h1>
        </div>
        <div class="topbar-right">
            ${rightHtml}
            <button class="theme-toggle" id="themeToggle" onclick="toggleTheme()" title="Toggle dark mode">
                <i class="fas fa-moon"></i>
            </button>
            <button class="notification-bell" onclick="toggleNotificationPanel()" title="Notifications">
                <i class="fas fa-bell"></i>
                <span class="badge-count hidden" id="notifBadge">0</span>
            </button>
        </div>
    </div>`;
}

/**
 * Generate the notification slide-out panel HTML.
 */
function generateNotifPanel() {
    return `
    <div class="slide-overlay" id="notifOverlay" onclick="closeNotificationPanel()"></div>
    <div class="notif-panel" id="notifPanel">
        <div class="panel-header">
            <h3><i class="fas fa-bell"></i> Notifications</h3>
            <div style="display:flex;gap:8px;align-items:center;">
                <button class="btn btn-sm btn-ghost" onclick="markAllNotifsRead()">Mark all read</button>
                <button class="panel-close" onclick="closeNotificationPanel()"><i class="fas fa-times"></i></button>
            </div>
        </div>
        <div id="notifBody"></div>
    </div>`;
}

// ═══════════════════════════════════════════════════════════════════════════
//  Init (call on every page)
// ═══════════════════════════════════════════════════════════════════════════

function initLeadFlow() {
    initTheme();
    loadUser();
    loadNotificationCount();
    initRippleEffects();
    initScrollAnimations();

    // Inject Inter font if not present
    if (!document.querySelector('link[href*="fonts.googleapis.com/css2?family=Inter"]')) {
        const fontLink = document.createElement('link');
        fontLink.rel = 'stylesheet';
        fontLink.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap';
        document.head.appendChild(fontLink);
    }

    // Inject PWA meta tags if not already present
    if (!document.querySelector('link[rel="manifest"]')) {
        const manifest = document.createElement('link');
        manifest.rel = 'manifest';
        manifest.href = '/manifest.json';
        document.head.appendChild(manifest);
    }
    if (!document.querySelector('meta[name="theme-color"]')) {
        const tc = document.createElement('meta');
        tc.name = 'theme-color';
        tc.content = '#e94560';
        document.head.appendChild(tc);
    }
    if (!document.querySelector('meta[name="apple-mobile-web-app-capable"]')) {
        const am = document.createElement('meta');
        am.name = 'apple-mobile-web-app-capable';
        am.content = 'yes';
        document.head.appendChild(am);
    }

    // Keyboard: Escape closes panels
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            closeNotificationPanel();
            closeSidebar();
        }
    });

    // Smooth page load animation
    document.body.style.opacity = '0';
    requestAnimationFrame(() => {
        document.body.style.transition = 'opacity 0.4s ease';
        document.body.style.opacity = '1';
    });
}

// ═══════════════════════════════════════════════════════════════════════════
//  PWA Registration
// ═══════════════════════════════════════════════════════════════════════════

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(() => {});
}
