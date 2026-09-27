// ===============================================
// CIVICPULSE AI - Chart Configuration
// ===============================================

const ChartConfig = {
    // Color scheme matching CSS variables
    colors: {
        primary: '#1e3a8a',
        secondary: '#3b82f6',
        success: '#22c55e',
        warning: '#f59e0b',
        danger: '#ef4444',
        gray: '#9ca3af'
    },
    
    // Common chart options
    defaultOptions: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
            legend: {
                position: 'bottom',
                labels: {
                    font: { size: 12 },
                    padding: 15,
                    usePointStyle: true
                }
            },
            tooltip: {
                backgroundColor: 'rgba(0, 0, 0, 0.8)',
                padding: 12,
                titleFont: { size: 13, weight: 'bold' },
                bodyFont: { size: 12 }
            }
        }
    },
    
    // Bar Chart Configuration
    barChart: function(canvasId, labels, data, label = 'Requests') {
        if (!document.getElementById(canvasId)) return null;
        
        const ctx = document.getElementById(canvasId).getContext('2d');
        return new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: label,
                    data: data,
                    backgroundColor: this.colors.primary,
                    borderColor: this.colors.primary,
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: {
                ...this.defaultOptions,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1
                        }
                    }
                }
            }
        });
    },
    
    // Doughnut Chart Configuration
    doughnutChart: function(canvasId, labels, data) {
        if (!document.getElementById(canvasId)) return null;
        
        const ctx = document.getElementById(canvasId).getContext('2d');
        const colors = {
            'Low': this.colors.success,
            'Moderate': this.colors.warning,
            'High': this.colors.danger
        };
        
        return new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: labels.map(l => colors[l] || this.colors.gray),
                    borderColor: '#fff',
                    borderWidth: 2
                }]
            },
            options: {
                ...this.defaultOptions,
                cutout: '65%'
            }
        });
    },
    
    // Line Chart Configuration
    lineChart: function(canvasId, labels, data, label = 'Requests') {
        if (!document.getElementById(canvasId)) return null;
        
        const ctx = document.getElementById(canvasId).getContext('2d');
        return new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: label,
                    data: data,
                    borderColor: this.colors.primary,
                    backgroundColor: 'rgba(30, 58, 138, 0.1)',
                    tension: 0.4,
                    fill: true,
                    pointBackgroundColor: this.colors.primary,
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 4
                }]
            },
            options: {
                ...this.defaultOptions,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    },
    
    // Horizontal Bar Chart
    horizontalBarChart: function(canvasId, labels, data, label = 'Count') {
        if (!document.getElementById(canvasId)) return null;
        
        const ctx = document.getElementById(canvasId).getContext('2d');
        return new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: label,
                    data: data,
                    backgroundColor: this.colors.primary,
                    borderRadius: 4
                }]
            },
            options: {
                ...this.defaultOptions,
                indexAxis: 'y',
                scales: {
                    x: {
                        beginAtZero: true
                    }
                }
            }
        });
    },
    
    // Render category distribution
    renderCategoryChart: function(data) {
        const labels = Object.keys(data);
        const values = Object.values(data);
        return this.barChart('categoryChart', labels, values, 'Requests by Category');
    },
    
    // Render urgency distribution
    renderUrgencyChart: function(data) {
        const labels = Object.keys(data);
        const values = Object.values(data);
        return this.doughnutChart('urgencyChart', labels, values);
    }
};

// Make available globally
window.ChartConfig = ChartConfig;