// ===============================================
// CIVICPULSE AI - Main Script
// ===============================================

// Mobile Navigation
const hamburger = document.getElementById('hamburger');
const navMenu = document.getElementById('navMenu');

if (hamburger) {
    hamburger.addEventListener('click', function() {
        navMenu.classList.toggle('active');
    });
    
    // Close menu when a link is clicked
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', () => {
            navMenu.classList.remove('active');
        });
    });
}

// Flash Messages - Auto-hide after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.animation = 'slideOut 300ms ease-in forwards';
            setTimeout(() => alert.remove(), 300);
        }, 5000);
    });
});

// Add slideOut animation
const style = document.createElement('style');
style.textContent = `
    @keyframes slideOut {
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// Password Visibility Toggle
function togglePassword(fieldId) {
    const field = document.getElementById(fieldId);
    if (field) {
        field.type = field.type === 'password' ? 'text' : 'password';
    }
}

// Form Validation
function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function validateUsername(username) {
    return username.length >= 3 && /^[a-zA-Z0-9_]+$/.test(username);
}

// Character Counter
function setupCharCounter(textareaId, counterId) {
    const textarea = document.getElementById(textareaId);
    const counter = document.getElementById(counterId);
    
    if (textarea && counter) {
        textarea.addEventListener('input', () => {
            counter.textContent = textarea.value.length;
        });
    }
}

// Generic Form Submission Prevention
function preventDuplicateSubmit(formId) {
    const form = document.getElementById(formId);
    if (form) {
        form.addEventListener('submit', function(e) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Processing...';
            }
        });
    }
}

// Confirmation Dialog
function confirmAction(message) {
    return confirm(message);
}

// Show Loading State
function showLoading(element, message = 'Loading...') {
    if (element) {
        element.disabled = true;
        element.innerHTML = `<span class="spinner"></span> ${message}`;
    }
}

function hideLoading(element, originalText) {
    if (element) {
        element.disabled = false;
        element.textContent = originalText;
    }
}

// Safe Fetch Wrapper
async function safeFetch(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('Fetch error:', error);
        showNotification(`Error: ${error.message}`, 'error');
        return null;
    }
}

// Notification System
function showNotification(message, type = 'info') {
    const container = document.getElementById('flashContainer');
    if (!container) return;
    
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible`;
    alertDiv.setAttribute('role', 'alert');
    alertDiv.innerHTML = `
        <span class="alert-message">${message}</span>
        <button class="alert-close" onclick="this.parentElement.remove()">×</button>
    `;
    
    container.appendChild(alertDiv);
    
    setTimeout(() => {
        alertDiv.style.animation = 'slideOut 300ms ease-in forwards';
        setTimeout(() => alertDiv.remove(), 300);
    }, 5000);
}

// Category Change Handler
function onCategoryChange() {
    const category = document.getElementById('category');
    if (category) {
        category.addEventListener('change', function() {
            // Can add dynamic behavior here if needed
        });
    }
}

// State Change Handler (for district cascade)
function onStateChange() {
    const stateSelect = document.getElementById('state');
    const districtSelect = document.getElementById('district');
    
    if (stateSelect && districtSelect) {
        stateSelect.addEventListener('change', function() {
            // In a real app, this would fetch districts for the state
            // For now, just clear the district field
            districtSelect.value = '';
        });
    }
}

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', function() {
    // Setup any forms on the page
    setupCharCounter('description', 'charCount');
    onCategoryChange();
    onStateChange();
    
    // Prevent duplicate form submissions
    preventDuplicateSubmit('requestForm');
    preventDuplicateSubmit('registerForm');
});

// Accessibility - Skip to main content link
function setupSkipLink() {
    const skipLink = document.createElement('a');
    skipLink.href = '#main-content';
    skipLink.textContent = 'Skip to main content';
    skipLink.style.cssText = `
        position: absolute;
        top: -40px;
        left: 0;
        background: var(--primary-color);
        color: white;
        padding: 8px;
        text-decoration: none;
        z-index: 100;
    `;
    
    skipLink.addEventListener('focus', () => {
        skipLink.style.top = '0';
    });
    
    skipLink.addEventListener('blur', () => {
        skipLink.style.top = '-40px';
    });
    
    if (document.body) {
        document.body.insertBefore(skipLink, document.body.firstChild);
    }
}

setupSkipLink();

// Export for use in other scripts
window.CivicPulse = {
    showNotification,
    safeFetch,
    confirmAction,
    showLoading,
    hideLoading,
    validateEmail,
    validateUsername
};