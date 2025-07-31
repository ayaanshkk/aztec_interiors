<template>
  <div class="layout-wrapper">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <h2>Aztec Interiors</h2>
      </div>
      <nav class="sidebar-nav">
        <ul>
          <li><a href="#" @click="setActiveView('dashboard')" :class="{ active: activeView === 'dashboard' }">Dashboard</a></li>
          <li><a href="#" @click="setActiveView('camera')" :class="{ active: activeView === 'camera' }">Take Photo</a></li>
          <li><a href="#" @click="setActiveView('upload')" :class="{ active: activeView === 'upload' }">Upload Image</a></li>
          <li><a href="#" @click="setActiveView('reports')" :class="{ active: activeView === 'reports' }">Reports</a></li>
          <li><a href="#" @click="setActiveView('settings')" :class="{ active: activeView === 'settings' }">Settings</a></li>
        </ul>
      </nav>
    </aside>

    <!-- Main content -->
    <main class="content">
      <header class="header-bar">
        <h1>{{ getPageTitle() }}</h1>
        <PrimeButton label="Logout" icon="pi pi-sign-out" class="p-button-danger" />
      </header>

      <!-- Dashboard View -->
      <section v-if="activeView === 'dashboard'" class="dashboard-section">
        <div class="stats-grid">
          <div class="stat-card">
            <h3>Forms Processed</h3>
            <p class="stat-number">{{ processingStats.totalProcessed }}</p>
          </div>
          <div class="stat-card">
            <h3>This Month</h3>
            <p class="stat-number">{{ processingStats.thisMonth }}</p>
          </div>
          <div class="stat-card">
            <h3>Pending</h3>
            <p class="stat-number">{{ processingStats.pending }}</p>
          </div>
        </div>

        <!-- Latest Processed Data -->
        <div v-if="latestExtractedData" class="latest-data-section">
          <div class="section-header">
            <h3><i class="pi pi-file-check mr-2"></i>Latest Processed Form</h3>
            <div class="header-actions">
              <PrimeButton
                label="Clear"
                icon="pi pi-times"
                @click="clearLatestData"
                class="p-button-sm p-button-text"
              />
              <PrimeButton
                label="Download PDF"
                icon="pi pi-file-pdf"
                class="p-button-success p-button-sm"
                @click="downloadFile(latestExtractedData.pdfUrl)"
                v-if="latestExtractedData.pdfUrl"
              />
              <PrimeButton
                label="Download Excel"
                icon="pi pi-file-excel"
                class="p-button-info p-button-sm"
                @click="downloadFile(latestExtractedData.excelUrl)"
                v-if="latestExtractedData.excelUrl"
              />
            </div>
          </div>

          <!-- Quick Summary -->
          <div class="data-summary">
            <div class="summary-stats">
              <div class="summary-item">
                <span class="summary-label">Customer:</span>
                <span class="summary-value">{{ latestExtractedData.data.customer_name || 'Not specified' }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">Address:</span>
                <span class="summary-value">{{ latestExtractedData.data.address || 'Not specified' }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">Room:</span>
                <span class="summary-value">{{ latestExtractedData.data.room || 'Not specified' }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">Phone:</span>
                <span class="summary-value">{{ latestExtractedData.data.tel_mob_number || 'Not specified' }}</span>
              </div>
            </div>
            <div class="completion-circle">
              <div class="circle-progress" :style="{ '--progress': latestExtractedData.completionPercentage + '%' }">
                <span class="completion-text">{{ latestExtractedData.completionPercentage }}%</span>
                <small>Complete</small>
              </div>
            </div>
          </div>

          <!-- Compact Data Preview -->
          <div class="data-preview">
            <h4>Complete Form Data</h4>

            <!-- Customer Information Row -->
            <div class="form-row">
              <div class="form-group">
                <label>CUSTOMER NAME</label>
                <div class="form-field">{{ latestExtractedData.data.customer_name || '' }}</div>
              </div>
              <div class="form-group">
                <label>SURVEY DATE</label>
                <div class="form-field">{{ latestExtractedData.data.survey_date || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>ADDRESS</label>
                <div class="form-field">{{ latestExtractedData.data.address || '' }}</div>
              </div>
              <div class="form-group">
                <label>APPT DATE</label>
                <div class="form-field">{{ latestExtractedData.data.appt_date || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>ROOM</label>
                <div class="form-field">{{ latestExtractedData.data.room || '' }}</div>
              </div>
              <div class="form-group">
                <label>PRO INST DATE</label>
                <div class="form-field">{{ latestExtractedData.data.pro_inst_date || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>TEL / MOB. NUMBER</label>
                <div class="form-field">{{ latestExtractedData.data.tel_mob_number || '' }}</div>
              </div>
              <div class="form-group">
                <label>COMP CHK DATE</label>
                <div class="form-field">{{ latestExtractedData.data.comp_chk_date || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label></label>
                <div class="form-field"></div>
              </div>
              <div class="form-group">
                <label>DATE DEPOSIT PAID</label>
                <div class="form-field">{{ latestExtractedData.data.date_deposit_paid || '' }}</div>
              </div>
            </div>

            <!-- Style Section -->
            <div class="form-section-title">Style & Colors</div>

            <div class="form-row">
              <div class="form-group">
                <label>FITTING STYLE</label>
                <div class="form-field">{{ latestExtractedData.data.fitting_style || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>DOOR STYLE</label>
                <div class="form-field">{{ latestExtractedData.data.door_style || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>DOOR COLOUR</label>
                <div class="form-field">{{ latestExtractedData.data.door_colour || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>END PANEL COLOUR</label>
                <div class="form-field">{{ latestExtractedData.data.end_panel_colour || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>PLINTH/FILLER COLOUR</label>
                <div class="form-field">{{ latestExtractedData.data.plinth_filler_colour || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>WORKTOP COLOUR</label>
                <div class="form-field">{{ latestExtractedData.data.worktop_colour || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>CABINET COLOUR</label>
                <div class="form-field">{{ latestExtractedData.data.cabinet_colour || '' }}</div>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>HANDLES CODE/QTY/SIZE</label>
                <div class="form-field">{{ latestExtractedData.data.handles_code_qty_size || '' }}</div>
              </div>
            </div>

            <!-- Bedside Cabinets Section -->
            <div class="form-section-title">Bedside Cabinets</div>
            <div class="checkbox-row">
              <div class="checkbox-group">
                <label>FLOATING</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.bedside_cabinets_floating)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>FITTED</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.bedside_cabinets_fitted)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>FREESTAND</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.bedside_cabinets_freestand)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="form-group">
                <label>QTY</label>
                <div class="form-field">{{ latestExtractedData.data.bedside_cabinets_qty || '' }}</div>
              </div>
            </div>

            <!-- Dresser/Desk Section -->
            <div class="form-section-title">Dresser / Desk</div>
            <div class="checkbox-row">
              <div class="checkbox-group">
                <label>YES</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.dresser_desk_yes)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>NO</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.dresser_desk_no)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="form-group">
                <label>QTY/SIZE</label>
                <div class="form-field">{{ latestExtractedData.data.dresser_desk_qty_size || '' }}</div>
              </div>
            </div>

            <!-- Internal Mirror Section -->
            <div class="form-section-title">Internal Mirror</div>
            <div class="checkbox-row">
              <div class="checkbox-group">
                <label>YES</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.internal_mirror_yes)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>NO</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.internal_mirror_no)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="form-group">
                <label>QTY/SIZE</label>
                <div class="form-field">{{ latestExtractedData.data.internal_mirror_qty_size || '' }}</div>
              </div>
            </div>

            <!-- Mirror Section -->
            <div class="form-section-title">Mirror</div>
            <div class="checkbox-row">
              <div class="checkbox-group">
                <label>SILVER</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.mirror_silver)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>BRONZE</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.mirror_bronze)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>GREY</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.mirror_grey)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="form-group">
                <label>QTY</label>
                <div class="form-field">{{ latestExtractedData.data.mirror_qty || '' }}</div>
              </div>
            </div>

            <!-- Soffit Lights Section -->
            <div class="form-section-title">Soffit Lights</div>
            <div class="checkbox-row">
              <div class="checkbox-group">
                <label>SPOT</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.soffit_lights_spot)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>STRIP</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.soffit_lights_strip)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="form-group">
                <label>COLOUR</label>
                <div class="form-field">{{ latestExtractedData.data.soffit_lights_colour || '' }}</div>
              </div>
            </div>
            <div class="checkbox-row">
              <div class="checkbox-group">
                <label>COOL WHITE</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.soffit_lights_cool_white)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>WARM WHITE</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.soffit_lights_warm_white)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="form-group">
                <label>QTY</label>
                <div class="form-field">{{ latestExtractedData.data.soffit_lights_qty || '' }}</div>
              </div>
            </div>

            <!-- Gable Lights Section -->
            <div class="form-section-title">Gable Lights</div>
            <div class="checkbox-row">
              <div class="form-group">
                <label>COLOUR</label>
                <div class="form-field">{{ latestExtractedData.data.gable_lights_colour || '' }}</div>
              </div>
              <div class="form-group">
                <label>PROFILE COLOUR</label>
                <div class="form-field">{{ latestExtractedData.data.gable_lights_profile_colour || '' }}</div>
              </div>
            </div>
            <div class="checkbox-row">
              <div class="checkbox-group">
                <label>BLACK</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.gable_lights_black)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>WHITE</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.gable_lights_white)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="form-group">
                <label>QTY</label>
                <div class="form-field">{{ latestExtractedData.data.gable_lights_qty || '' }}</div>
              </div>
            </div>

            <!-- Other/Misc/Accessories Section -->
            <div class="form-section-title">Other / Misc / Accessories</div>
            <div class="checkbox-row">
              <div class="checkbox-group">
                <label>Carpet protection</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.carpet_protection)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>Floor Tile protection</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.floor_tile_protection)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
              <div class="checkbox-group">
                <label>No floor</label>
                <div class="checkbox-field">
                  <span v-if="isChecked(latestExtractedData.data.no_floor)" class="checkbox checked">✓</span>
                  <span v-else class="checkbox"></span>
                </div>
              </div>
            </div>

            <!-- Terms and Signature Section -->
            <div class="form-section-title">Terms & Signature</div>
            <div class="form-row">
              <div class="form-group">
                <label>DATE TERMS AND CONDITIONS GIVEN</label>
                <div class="form-field">{{ latestExtractedData.data.date_terms_conditions_given || '' }}</div>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>GAS & ELECTRIC INSTALLATION TERMS GIVEN</label>
                <div class="form-field">{{ latestExtractedData.data.gas_electric_installation_terms_given || '' }}</div>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>Customer Signature:</label>
                <div class="form-field">{{ latestExtractedData.data.customer_signature || '' }}</div>
              </div>
              <div class="form-group">
                <label>Date:</label>
                <div class="form-field">{{ latestExtractedData.data.signature_date || '' }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="quick-actions">
          <h3>Quick Actions</h3>
          <div class="action-buttons">
            <PrimeButton label="Take Photo & Process" icon="pi pi-camera" @click="setActiveView('camera')" class="p-button-primary p-button-lg" />
            <PrimeButton label="Upload Image" icon="pi pi-upload" @click="setActiveView('upload')" class="p-button-info" />
            <PrimeButton label="View Reports" icon="pi pi-chart-bar" @click="setActiveView('reports')" class="p-button-success" />
          </div>
        </div>
      </section>

      <!-- Camera Capture View -->
      <section v-if="activeView === 'camera'" class="camera-section">
        <CameraCapture @back="setActiveView('dashboard')" @data-processed="onDataProcessed" />
      </section>

      <!-- Upload View -->
      <section v-if="activeView === 'upload'" class="upload-section">
        <h2>Upload Form Image</h2>
        <p>Upload an image of your bedroom checklist form for instant processing.</p>
        <UploadForm @data-processed="onDataProcessed" />
      </section>

      <!-- Reports View -->
      <section v-if="activeView === 'reports'" class="reports-section">
        <h2>Reports</h2>
        <p>View and manage your processed forms.</p>
        <div class="coming-soon">
          <i class="pi pi-chart-bar" style="font-size: 3rem; color: #ccc;"></i>
          <p>Reports feature coming soon...</p>
        </div>
      </section>

      <!-- Settings View -->
      <section v-if="activeView === 'settings'" class="settings-section">
        <h2>Settings</h2>
        <p>Configure your application settings.</p>
        <div class="coming-soon">
          <i class="pi pi-cog" style="font-size: 3rem; color: #ccc;"></i>
          <p>Settings feature coming soon...</p>
        </div>
      </section>
    </main>
  </div>
</template>

<script>
import UploadForm from './components/UploadForm.vue';
import CameraCapture from './components/CameraCapture.vue';
import PrimeButton from 'primevue/button';

export default {
  components: {
    UploadForm,
    CameraCapture,
    PrimeButton
  },
  data() {
    return {
      activeView: 'dashboard',
      latestExtractedData: null,
      processingStats: {
        totalProcessed: 42,
        thisMonth: 12,
        pending: 3
      }
    };
  },
  provide() {
    return {
      onDataProcessed: this.onDataProcessed,
      latestExtractedData: () => this.latestExtractedData
    };
  },
  methods: {
    setActiveView(view) {
      this.activeView = view;
    },
    getPageTitle() {
      switch(this.activeView) {
        case 'dashboard': return 'Dashboard';
        case 'camera': return 'Take Photo';
        case 'upload': return 'Upload Image';
        case 'reports': return 'Reports';
        case 'settings': return 'Settings';
        default: return 'Dashboard';
      }
    },
    onDataProcessed(processedData) {
      // Calculate completion percentage
      const filledFields = Object.values(processedData.data).filter(value =>
        value && value.toString().trim() !== ''
      ).length;
      const totalFields = Object.keys(processedData.data).length;
      const completionPercentage = Math.round((filledFields / totalFields) * 100);

      this.latestExtractedData = {
        ...processedData,
        completionPercentage,
        timestamp: new Date().toLocaleString()
      };

      this.processingStats.totalProcessed += 1;
      this.processingStats.thisMonth += 1;

      // Auto switch to dashboard to show results
      setTimeout(() => {
        this.setActiveView('dashboard');
      }, 2000);
    },
    clearLatestData() {
      this.latestExtractedData = null;
    },
    downloadFile(url) {
      if (url) {
        window.open(url, '_blank');
      }
    },
    // Enhanced checkbox checking method
    isChecked(value) {
      // Only return true if the value is exactly "✓" or the string "true"
      return value === '✓' || value === 'true' || value === true;
    },
    getKeyFields() {
      if (!this.latestExtractedData) return [];

      const keyFieldsMap = {
        'fitting_style': 'Fitting Style',
        'door_style': 'Door Style',
        'door_colour': 'Door Colour',
        'bedside_cabinets_qty': 'Bedside Cabinets Qty',
        'dresser_desk_yes': 'Dresser/Desk',
        'internal_mirror_yes': 'Internal Mirror',
        'mirror_silver': 'Silver Mirror',
        'soffit_lights_spot': 'Spot Lights',
        'gable_lights_black': 'Black Gable Lights'
      };

      return Object.entries(keyFieldsMap)
        .map(([key, label]) => ({
          field: label,
          value: this.latestExtractedData.data[key]
        }))
        .filter(item => item.value && item.value.toString().trim() !== '');
    }
  }
};
</script>

<style scoped>
/* Reset and base styles */
* {
  box-sizing: border-box;
}

.layout-wrapper {
  display: flex;
  min-height: 100vh;
  background-color: #f8fafc;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  color: #1e293b;
}

/* Sidebar styles */
.sidebar {
  width: 280px;
  background: linear-gradient(145deg, #1e293b, #334155);
  box-shadow: 4px 0 12px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  padding: 2rem;
  position: fixed;
  height: 100vh;
  overflow-y: auto;
}

.sidebar-header h2 {
  font-size: 1.875rem;
  margin-bottom: 2.5rem;
  color: #ffffff;
  font-weight: 700;
  text-align: center;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  user-select: none;
}

.sidebar-nav ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.sidebar-nav li {
  margin-bottom: 0.75rem;
}

.sidebar-nav a {
  color: #cbd5e1;
  text-decoration: none;
  font-weight: 500;
  padding: 1rem 1.25rem;
  display: block;
  border-radius: 10px;
  transition: all 0.3s ease;
  cursor: pointer;
}

.sidebar-nav a:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
  transform: translateX(4px);
}

.sidebar-nav a.active {
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  color: white;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

/* Main content styles */
.content {
  flex-grow: 1;
  margin-left: 280px;
  padding: 2rem 3rem;
  background: #ffffff;
  min-height: 100vh;
}

/* Header bar */
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2.5rem;
  padding: 1.5rem 2rem;
  background: linear-gradient(135deg, #f8fafc, #e2e8f0);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.header-bar h1 {
  font-size: 2.25rem;
  font-weight: 700;
  margin: 0;
  color: #1e293b;
}

/* Dashboard specific styles */
.dashboard-section {
  display: flex;
  flex-direction: column;
  gap: 2.5rem;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1.5rem;
}

.stat-card {
  background: linear-gradient(135deg, #ffffff, #f8fafc);
  padding: 2rem;
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border: 1px solid #e2e8f0;
  text-align: center;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.stat-card h3 {
  font-size: 1rem;
  color: #64748b;
  margin: 0 0 1rem 0;
  font-weight: 500;
}

.stat-number {
  font-size: 3rem;
  font-weight: 700;
  color: #3b82f6;
  margin: 0;
  line-height: 1;
}

.quick-actions {
  background: linear-gradient(135deg, #ffffff, #f8fafc);
  padding: 2.5rem;
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border: 1px solid #e2e8f0;
}

.quick-actions h3 {
  font-size: 1.5rem;
  margin-bottom: 1.5rem;
  color: #1e293b;
  font-weight: 600;
}

.action-buttons {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}

.action-buttons .p-button-lg {
  padding: 1rem 2rem;
  font-size: 1.1rem;
  font-weight: 600;
}

/* Camera and Upload section styles */
.camera-section, .upload-section {
  background: linear-gradient(135deg, #ffffff, #f8fafc);
  padding: 2.5rem;
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border: 1px solid #e2e8f0;
}

/* Latest Data Section */
.latest-data-section {
  background: linear-gradient(135deg, #ffffff, #f0f9ff);
  border: 1px solid #bae6fd;
  border-radius: 16px;
  padding: 2rem;
  margin-bottom: 2.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.section-header h3 {
  color: #0c4a6e;
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.data-summary {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 2rem;
  gap: 2rem;
  flex-wrap: wrap;
}

.summary-stats {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.summary-label {
  font-size: 0.875rem;
  color: #64748b;
  font-weight: 500;
}

.summary-value {
  font-size: 1rem;
  color: #1e293b;
  font-weight: 600;
}

.completion-circle {
  display: flex;
  align-items: center;
  justify-content: center;
}

.circle-progress {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: conic-gradient(#3b82f6 var(--progress), #e5e7eb var(--progress));
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
}

.circle-progress::before {
  content: '';
  position: absolute;
  width: 90px;
  height: 90px;
  border-radius: 50%;
  background: white;
}

.completion-text {
  font-size: 1.5rem;
  font-weight: 700;
  color: #3b82f6;
  z-index: 1;
}

.completion-circle small {
  font-size: 0.75rem;
  color: #64748b;
  z-index: 1;
}

.debug-section {
  margin-bottom: 1rem;
  padding: 1rem;
  background: #f3f4f6;
  border-radius: 8px;
  border: 1px solid #d1d5db;
}

.debug-section h5 {
  margin: 0 0 0.5rem 0;
  color: #374151;
  font-size: 0.875rem;
}

.data-preview {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e0f2fe;
}

.data-preview h4 {
  margin: 0 0 1.5rem 0;
  color: #1e293b;
  font-size: 1.25rem;
  text-align: center;
  padding-bottom: 0.75rem;
  border-bottom: 2px solid #e2e8f0;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 0.5rem;
}

.form-group {
  display: flex;
  flex-direction: column;
}

.form-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #374151;
  background: #f8fafc;
  padding: 0.25rem 0.5rem;
  border: 1px solid #d1d5db;
  border-bottom: none;
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

.form-field {
  min-height: 2rem;
  padding: 0.5rem;
  border: 1px solid #d1d5db;
  background: white;
  font-weight: 500;
  color: #1f2937;
  display: flex;
  align-items: center;
}

.form-section-title {
  font-size: 1rem;
  font-weight: 700;
  color: #1e293b;
  background: linear-gradient(135deg, #e2e8f0, #cbd5e1);
  padding: 0.75rem;
  margin: 1.5rem 0 0.75rem 0;
  border-radius: 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  text-align: center;
}

.checkbox-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 1rem;
  margin-bottom: 0.5rem;
  align-items: end;
}

.checkbox-group {
  display: flex;
  flex-direction: column;
}

.checkbox-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #374151;
  background: #f8fafc;
  padding: 0.25rem 0.5rem;
  border: 1px solid #d1d5db;
  border-bottom: none;
  text-transform: uppercase;
  letter-spacing: 0.025em;
  text-align: center;
}

.checkbox-field {
  height: 2rem;
  border: 1px solid #d1d5db;
  background: white;
  display: flex;
  align-items: center;
  justify-content: center;
}

.checkbox {
  width: 1.25rem;
  height: 1.25rem;
  border: 2px solid #d1d5db;
  background: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 1rem;
}

.checkbox.checked {
  background: #10b981;
  color: white;
  border-color: #10b981;
}

.upload-section h2, .reports-section h2, .settings-section h2 {
  margin-top: 0;
  font-weight: 700;
  margin-bottom: 1rem;
  color: #1e293b;
  font-size: 1.875rem;
}

.upload-section p, .reports-section p, .settings-section p {
  color: #64748b;
  margin-bottom: 2rem;
  font-size: 1.125rem;
}

.coming-soon {
  text-align: center;
  padding: 4rem 2rem;
  color: #94a3b8;
}

.coming-soon p {
  font-size: 1.25rem;
  margin-top: 1rem;
}

/* Responsive design */
@media (max-width: 1024px) {
  .sidebar {
    width: 240px;
  }

  .content {
    margin-left: 240px;
    padding: 1.5rem 2rem;
  }
}

@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);
    transition: transform 0.3s ease;
  }

  .content {
    margin-left: 0;
    padding: 1rem;
  }

  .header-bar {
    flex-direction: column;
    gap: 1rem;
    text-align: center;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .action-buttons {
    flex-direction: column;
  }

  .form-row {
    grid-template-columns: 1fr;
  }

  .checkbox-row {
    grid-template-columns: 1fr;
  }

  .data-summary {
    flex-direction: column;
  }

  .summary-stats {
    grid-template-columns: 1fr;
  }
}
</style>
