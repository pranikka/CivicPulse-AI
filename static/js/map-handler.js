// ===============================================
// CIVICPULSE AI - Map & Hotspot Handler
// ===============================================

const MapHandler = {
    hotspots: [],
    filteredHotspots: [],
    
    // Initialize map
    init: async function() {
        await this.loadHotspots();
        this.setupFilters();
        this.render();
    },
    
    // Load hotspots from API
    loadHotspots: async function() {
        const data = await window.CivicPulse.safeFetch('/api/hotspots');
        if (data && Array.isArray(data)) {
            this.hotspots = data;
            this.filteredHotspots = [...this.hotspots];
        } else {
            this.hotspots = this.getMockData();
            this.filteredHotspots = [...this.hotspots];
        }
    },
    
    // Mock data for demo
    getMockData: function() {
        return [
            {
                state: 'Tamil Nadu',
                district: 'Salem',
                demand: 2840,
                gap: 8.4,
                population: 1200000,
                projects: 3,
                color: 'red'
            },
            {
                state: 'Maharashtra',
                district: 'Nashik',
                demand: 2150,
                gap: 7.8,
                population: 950000,
                projects: 2,
                color: 'red'
            },
            {
                state: 'Karnataka',
                district: 'Davangere',
                demand: 1890,
                gap: 7.5,
                population: 800000,
                projects: 2,
                color: 'orange'
            },
            {
                state: 'Telangana',
                district: 'Warangal',
                demand: 1650,
                gap: 6.9,
                population: 750000,
                projects: 1,
                color: 'orange'
            },
            {
                state: 'Andhra Pradesh',
                district: 'Vizag',
                demand: 1420,
                gap: 6.2,
                population: 1100000,
                projects: 3,
                color: 'orange'
            }
        ];
    },
    
    // Setup filter listeners
    setupFilters: function() {
        const stateSelect = document.getElementById('stateSelect');
        const gapFilter = document.getElementById('gapFilter');
        
        if (stateSelect) {
            stateSelect.addEventListener('change', () => this.applyFilters());
        }
        
        if (gapFilter) {
            gapFilter.addEventListener('change', () => this.applyFilters());
        }
    },
    
    // Apply filters
    applyFilters: function() {
        const state = document.getElementById('stateSelect')?.value || '';
        const gapLevel = document.getElementById('gapFilter')?.value || '';
        
        this.filteredHotspots = this.hotspots.filter(h => {
            // State filter
            if (state && h.state !== state) return false;
            
            // Gap level filter
            if (gapLevel) {
                if (gapLevel === 'high' && h.gap < 7) return false;
                if (gapLevel === 'moderate' && (h.gap < 4 || h.gap >= 7)) return false;
                if (gapLevel === 'low' && h.gap >= 4) return false;
            }
            
            return true;
        });
        
        this.render();
    },
    
    // Render hotspots
    render: function() {
        const mapContainer = document.getElementById('mapContainer');
        if (!mapContainer) return;
        
        // Render visualization
        this.renderMapVisualization();
        
        // Render table
        this.renderTable();
    },
    
    // Simple map visualization
    renderMapVisualization: function() {
        const mapContainer = document.getElementById('mapContainer');
        if (!mapContainer) return;
        
        // Create a simple grid-based visualization
        let html = '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 10px; padding: 20px;">';
        
        this.filteredHotspots.forEach(h => {
            const gapColor = h.gap >= 7 ? '#ef4444' : h.gap >= 4 ? '#f59e0b' : '#22c55e';
            html += `
                <div style="
                    background-color: ${gapColor};
                    color: white;
                    padding: 15px;
                    border-radius: 8px;
                    text-align: center;
                    cursor: pointer;
                    transition: transform 0.2s;
                "
                onmouseover="this.style.transform='scale(1.05)'"
                onmouseout="this.style.transform='scale(1)'"
                onclick="MapHandler.showDetail('${h.state}', '${h.district}')">
                    <div style="font-weight: bold; font-size: 14px;">${h.district}</div>
                    <div style="font-size: 12px; opacity: 0.9;">${h.state}</div>
                    <div style="font-size: 11px; opacity: 0.8;">Gap: ${h.gap}/10</div>
                </div>
            `;
        });
        
        html += '</div>';
        mapContainer.innerHTML = html;
    },
    
    // Render hotspots table
    renderTable: function() {
        const tableContainer = document.querySelector('.hotspots-table');
        if (!tableContainer) return;
        
        let html = `
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>District</th>
                        <th>State</th>
                        <th>Infrastructure Gap</th>
                        <th>Citizen Requests</th>
                        <th>Population</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        this.filteredHotspots.forEach((h, index) => {
            const gapClass = h.gap >= 7 ? 'high' : h.gap >= 4 ? 'moderate' : 'low';
            html += `
                <tr>
                    <td><strong>#${index + 1}</strong></td>
                    <td>${h.district}</td>
                    <td>${h.state}</td>
                    <td>
                        <div class="gap-badge gap-${gapClass}">
                            ${h.gap}/10
                        </div>
                    </td>
                    <td>${h.demand}</td>
                    <td>${(h.population / 1000000).toFixed(1)}M</td>
                    <td>
                        <button class="btn btn-sm btn-outline" onclick="MapHandler.showDetail('${h.state}', '${h.district}')">
                            Details
                        </button>
                    </td>
                </tr>
            `;
        });
        
        html += `
                </tbody>
            </table>
        `;
        
        tableContainer.innerHTML = html;
    },
    
    // Show hotspot details
    showDetail: function(state, district) {
        const hotspot = this.hotspots.find(h => h.state === state && h.district === district);
        if (hotspot) {
            const message = `
District: ${hotspot.district}, ${hotspot.state}
Infrastructure Gap: ${hotspot.gap}/10
Citizen Requests: ${hotspot.demand}
Population: ${(hotspot.population / 1000000).toFixed(1)}M
Ongoing Projects: ${hotspot.projects}

Category Breakdown:
- Roads: ${Math.floor(hotspot.demand * 0.35)}
- Water: ${Math.floor(hotspot.demand * 0.25)}
- Healthcare: ${Math.floor(hotspot.demand * 0.2)}
- Other: ${Math.floor(hotspot.demand * 0.2)}`;
            alert(message);
        }
    }
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    MapHandler.init();
});

// Make available globally
window.MapHandler = MapHandler;