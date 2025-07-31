<template>
  <div class="upload-container">
    <PrimeToast />

    <!-- Quick Upload Interface -->
    <div v-if="!loading && !extractedData" class="upload-interface">
      <div class="upload-header">
        <h2><i class="pi pi-upload mr-2"></i>Quick Form Upload</h2>
        <p>Drop your form image here or click to select - processing starts instantly!</p>
      </div>

      <!-- Drag & Drop Upload -->
      <div
        class="drop-zone"
        :class="{ 'drag-over': dragOver }"
        @drop="onDrop"
        @dragover.prevent="dragOver = true"
        @dragleave="dragOver = false"
        @click="$refs.fileInput.click()"
      >
        <div class="drop-content">
          <i class="pi pi-cloud-upload upload-icon"></i>
          <h3>Drop image here or click to select</h3>
          <p>Supports JPG, PNG, GIF up to 16MB</p>
          <PrimeButton
            label="Select File"
            icon="pi pi-folder-open"
            class="p-button-primary p-button-lg mt-3"
          />
        </div>
        <input
          ref="fileInput"
          type="file"
          accept="image/*"
          @change="onFileSelect"
          style="display: none;"
        />
      </div>
    </div>

    <!-- Instant Processing -->
    <div v-if="loading" class="processing-section">
      <div class="processing-animation">
        <div class="processing-circle">
          <ProgressSpinner
            style="width: 80px; height: 80px"
            strokeWidth="3"
            fill="transparent"
            animationDuration="1s"
          />
        </div>
        <div class="processing-details">
          <h3>{{ processingMessage }}</h3>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
          </div>
          <p>{{ progressPercent }}% complete</p>
        </div>
      </div>

      <div class="processing-steps">
        <div class="step" :class="{ active: currentStep >= 1, complete: currentStep > 1 }">
          <i class="pi pi-eye"></i>
          <span>Reading Image</span>
        </div>
        <div class="step" :class="{ active: currentStep >= 2, complete: currentStep > 2 }">
          <i class="pi pi-cog"></i>
          <span>AI Processing</span>
        </div>
        <div class="step" :class="{ active: currentStep >= 3, complete: currentStep > 3 }">
          <i class="pi pi-check"></i>
          <span>Complete</span>
        </div>
      </div>
    </div>

    <!-- Instant Results -->
    <div v-if="extractedData && !loading" class="results-section">
      <div class="results-header">
        <div class="success-badge">
          <i class="pi pi-check-circle"></i>
          <span>Processing Complete in {{ processingTime }}s</span>
        </div>
        <div class="action-buttons">
          <PrimeButton
            label="Process Another"
            icon="pi pi-plus"
            @click="resetUpload"
            class="p-button-secondary"
          />
          <PrimeButton
            label="Download PDF"
            icon="pi pi-file-pdf"
            class="p-button-success"
            @click="downloadFile(pdfUrl)"
            v-if="pdfUrl"
          />
          <PrimeButton
            label="Download Excel"
            icon="pi pi-file-excel"
            class="p-button-info"
            @click="downloadFile(excelUrl)"
            v-if="excelUrl"
          />
        </div>
      </div>

      <!-- Quick Stats -->
      <div class="stats-row">
        <div class="stat-item">
          <span class="stat-number">{{ filledFieldsCount }}</span>
          <span class="stat-label">Fields Filled</span>
        </div>
        <div class="stat-item">
          <span class="stat-number">{{ totalFieldsCount }}</span>
          <span class="stat-label">Total Fields</span>
        </div>
        <div class="stat-item">
          <span class="stat-number">{{ Math.round((filledFieldsCount / totalFieldsCount) * 100) }}%</span>
          <span class="stat-label">Completion</span>
        </div>
      </div>

      <!-- Compact Data Table -->
      <div class="compact-table-container">
        <div class="table-header">
          <h4>Extracted Data</h4>
          <div class="table-controls">
            <InputText
              v-model="globalFilter"
              placeholder="Search..."
              class="search-input"
            />
            <PrimeButton
              :label="showAllData ? 'Show Key Fields' : 'Show All'"
              @click="showAllData = !showAllData"
              class="p-button-sm p-button-outlined"
            />
          </div>
        </div>

        <DataTable
          :value="displayData"
          class="p-datatable-sm compact-table"
          :paginator="showAllData"
          :rows="showAllData ? 10 : 1000"
          responsiveLayout="scroll"
          :globalFilterFields="['section', 'field', 'value']"
          :globalFilter="globalFilter"
        >
          <Column field="section" header="Section" style="width: 20%">
            <template #body="{ data }">
              <span v-if="data.section" class="section-tag">{{ data.section }}</span>
            </template>
          </Column>

          <Column field="field" header="Field" style="width: 35%">
            <template #body="{ data }">
              <span class="field-name">{{ data.field }}</span>
            </template>
          </Column>

          <Column field="value" header="Value" style="width: 35%">
            <template #body="{ data }">
              <span v-if="data.value" class="field-value">
                <i v-if="data.value === '✓'" class="pi pi-check text-green-600 font-bold"></i>
                <i v-else-if="data.value === '✗'" class="pi pi-times text-red-600 font-bold"></i>
                <span v-else class="value-text">{{ data.value }}</span>
              </span>
              <span v-else class="empty-value">—</span>
            </template>
          </Column>

          <Column field="confidence" header="Confidence" style="width: 10%">
            <template #body="{ data }">
              <div class="confidence-bar">
                <div
                  class="confidence-fill"
                  :style="{ width: (data.confidence || 85) + '%' }"
                  :class="{
                    'high': (data.confidence || 85) >= 80,
                    'medium': (data.confidence || 85) >= 50 && (data.confidence || 85) < 80,
                    'low': (data.confidence || 85) < 50
                  }"
                ></div>
              </div>
            </template>
          </Column>
        </DataTable>
      </div>
    </div>

    <!-- Error Display -->
    <div v-if="error" class="error-section">
      <div class="error-content">
        <i class="pi pi-exclamation-triangle"></i>
        <h3>Upload Failed</h3>
        <p>{{ error }}</p>
        <PrimeButton
          label="Try Again"
          icon="pi pi-refresh"
          @click="resetUpload"
          class="p-button-primary"
        />
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'UploadForm',
  emits: ['data-processed'],
  data() {
    return {
      dragOver: false,
      extractedData: null,
      pdfUrl: null,
      excelUrl: null,
      loading: false,
      error: null,
      globalFilter: null,
      showAllData: false,
      currentStep: 0,
      processingMessage: 'Starting...',
      progressPercent: 0,
      processingTime: 0,
      processingStartTime: null,
      progressInterval: null
    };
  },
  computed: {
    formattedData() {
      if (!this.extractedData) return [];

      const sections = {
        "Customer Information": [
          "customer_name", "address", "room", "tel_mob_number"
        ],
        "Important Dates": [
          "survey_date", "appt_date", "pro_inst_date", "comp_chk_date", "date_deposit_paid"
        ],
        "Style & Colors": [
          "fitting_style", "door_style", "door_colour", "end_panel_colour",
          "plinth_filler_colour", "worktop_colour", "cabinet_colour", "handles_code_qty_size"
        ],
        "Bedside Cabinets": [
          "bedside_cabinets_floating", "bedside_cabinets_fitted", "bedside_cabinets_freestand", "bedside_cabinets_qty"
        ],
        "Dresser/Desk": [
          "dresser_desk_yes", "dresser_desk_no", "dresser_desk_qty_size"
        ],
        "Internal Mirror": [
          "internal_mirror_yes", "internal_mirror_no", "internal_mirror_qty_size"
        ],
        "Mirror Options": [
          "mirror_silver", "mirror_bronze", "mirror_grey", "mirror_qty"
        ],
        "Soffit Lights": [
          "soffit_lights_spot", "soffit_lights_strip", "soffit_lights_colour",
          "soffit_lights_cool_white", "soffit_lights_warm_white", "soffit_lights_qty"
        ],
        "Gable Lights": [
          "gable_lights_colour", "gable_lights_profile_colour", "gable_lights_black",
          "gable_lights_white", "gable_lights_qty"
        ],
        "Accessories": [
          "carpet_protection", "floor_tile_protection", "no_floor"
        ],
        "Terms & Signature": [
          "date_terms_conditions_given", "gas_electric_installation_terms_given",
          "customer_signature", "signature_date"
        ]
      };

      const formattedData = [];

      for (const [sectionName, fields] of Object.entries(sections)) {
        for (const field of fields) {
          const fieldDisplay = field.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
          const value = this.extractedData[field];

          formattedData.push({
            section: sectionName,
            field: fieldDisplay,
            value: value || '',
            confidence: Math.floor(Math.random() * 30) + 70 // Mock confidence score
          });
        }
      }

      return formattedData;
    },

    displayData() {
      if (this.showAllData) {
        return this.formattedData;
      }
      // Show only filled fields for quick view
      return this.formattedData.filter(item => item.value && item.value.trim() !== '');
    },

    filledFieldsCount() {
      return this.formattedData.filter(item => item.value && item.value.trim() !== '').length;
    },

    totalFieldsCount() {
      return this.formattedData.length;
    }
  },
  methods: {
    onDrop(event) {
      event.preventDefault();
      this.dragOver = false;

      const files = event.dataTransfer.files;
      if (files.length > 0) {
        this.processImage(files[0]);
      }
    },

    onFileSelect(event) {
      const files = event.target.files;
      if (files.length > 0) {
        this.processImage(files[0]);
      }
    },

    async processImage(file) {
      // Instant start
      this.loading = true;
      this.error = null;
      this.processingStartTime = Date.now();
      this.currentStep = 1;
      this.processingMessage = 'Reading image...';
      this.progressPercent = 10;

      // Start progress animation
      this.startProgressAnimation();

      try {
        const formData = new FormData();
        formData.append('image', file);

        // Step 2: AI Processing
        this.currentStep = 2;
        this.processingMessage = 'AI is analyzing the form...';
        this.progressPercent = 40;

        const response = await fetch('http://localhost:5000/upload', {
          method: 'POST',
          body: formData,
        });

        this.progressPercent = 80;
        this.processingMessage = 'Generating files...';

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.error || `Server error: ${response.status}`);
        }

        if (data.success) {
          // Complete processing
          this.currentStep = 3;
          this.progressPercent = 100;
          this.processingMessage = 'Complete!';

          this.extractedData = data.structured_data;
          this.pdfUrl = `http://localhost:5000${data.pdf_download_url}`;
          this.excelUrl = `http://localhost:5000${data.excel_download_url}`;

          // Calculate processing time
          this.processingTime = ((Date.now() - this.processingStartTime) / 1000).toFixed(1);

          // Stop progress animation
          this.stopProgressAnimation();

          // Short delay for smooth UX
          setTimeout(() => {
            this.loading = false;

            // Emit the processed data to parent
            this.$emit('data-processed', {
              data: this.extractedData,
              pdfUrl: this.pdfUrl,
              excelUrl: this.excelUrl,
              processingTime: this.processingTime,
              filledFieldsCount: this.filledFieldsCount
            });

            this.$toast.add({
              severity: 'success',
              summary: `Processed in ${this.processingTime}s!`,
              detail: `${this.filledFieldsCount} fields extracted successfully`,
              life: 4000
            });

          }, 300);

        } else {
          throw new Error(data.error || 'Processing failed');
        }

      } catch (error) {
        console.error('Processing error:', error);
        this.error = error.message || 'Failed to process image';
        this.loading = false;
        this.stopProgressAnimation();

        this.$toast.add({
          severity: 'error',
          summary: 'Processing Failed',
          detail: this.error,
          life: 4000
        });
      }
    },

    startProgressAnimation() {
      this.progressInterval = setInterval(() => {
        if (this.progressPercent < 90) {
          this.progressPercent += Math.random() * 2;
        }
      }, 100);
    },

    stopProgressAnimation() {
      if (this.progressInterval) {
        clearInterval(this.progressInterval);
        this.progressInterval = null;
      }
    },

    resetUpload() {
      this.extractedData = null;
      this.pdfUrl = null;
      this.excelUrl = null;
      this.error = null;
      this.loading = false;
      this.currentStep = 0;
      this.progressPercent = 0;
      this.showAllData = false;
      this.globalFilter = null;
      this.stopProgressAnimation();

      // Reset file input
      if (this.$refs.fileInput) {
        this.$refs.fileInput.value = '';
      }
    },

    downloadFile(url) {
      if (url) {
        window.open(url, '_blank');
      }
    }
  },

  beforeUnmount() {
    this.stopProgressAnimation();
  }
};
</script>

<style scoped>
.upload-container {
  max-width: 1000px;
  margin: 0 auto;
}

.upload-interface {
  text-align: center;
}

.upload-header {
  margin-bottom: 2rem;
}

.upload-header h2 {
  color: #1e293b;
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.upload-header p {
  color: #64748b;
  font-size: 1.125rem;
}

.drop-zone {
  border: 3px dashed #cbd5e1;
  border-radius: 16px;
  padding: 3rem 2rem;
  background: linear-gradient(135deg, #f8fafc, #f1f5f9);
  cursor: pointer;
  transition: all 0.3s ease;
  margin-bottom: 2rem;
}

.drop-zone:hover,
.drop-zone.drag-over {
  border-color: #3b82f6;
  background: linear-gradient(135deg, #dbeafe, #e0f2fe);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.15);
}

.drop-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}

.upload-icon {
  font-size: 4rem;
  color: #64748b;
  margin-bottom: 1rem;
}

.drop-zone:hover .upload-icon,
.drop-zone.drag-over .upload-icon {
  color: #3b82f6;
  transform: scale(1.1);
}

.processing-section {
  text-align: center;
  padding: 3rem 2rem;
}

.processing-animation {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2rem;
  margin-bottom: 3rem;
}

.processing-circle {
  position: relative;
}

.processing-details h3 {
  color: #1e293b;
  margin-bottom: 1rem;
  font-size: 1.5rem;
}

.progress-bar {
  width: 300px;
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #10b981);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.processing-steps {
  display: flex;
  justify-content: center;
  gap: 2rem;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  border-radius: 12px;
  background: #f1f5f9;
  color: #94a3b8;
  transition: all 0.3s ease;
  min-width: 100px;
}

.step.active {
  background: #dbeafe;
  color: #3b82f6;
  transform: scale(1.05);
}

.step.complete {
  background: #dcfce7;
  color: #16a34a;
}

.step i {
  font-size: 1.5rem;
}

.step span {
  font-size: 0.875rem;
  font-weight: 600;
}

.results-section {
  margin-top: 2rem;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.success-badge {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: #dcfce7;
  color: #16a34a;
  padding: 0.75rem 1.5rem;
  border-radius: 50px;
  font-weight: 600;
}

.success-badge i {
  font-size: 1.25rem;
}

.action-buttons {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.stats-row {
  display: flex;
  justify-content: center;
  gap: 2rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1.5rem;
  background: linear-gradient(135deg, #ffffff, #f8fafc);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  min-width: 120px;
}

.stat-number {
  font-size: 2rem;
  font-weight: 700;
  color: #3b82f6;
  line-height: 1;
}

.stat-label {
  font-size: 0.875rem;
  color: #64748b;
  font-weight: 500;
  margin-top: 0.25rem;
}

.compact-table-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem;
  background: linear-gradient(135deg, #f8fafc, #e2e8f0);
  border-bottom: 1px solid #e2e8f0;
  flex-wrap: wrap;
  gap: 1rem;
}

.table-header h4 {
  margin: 0;
  color: #1e293b;
  font-size: 1.25rem;
}

.table-controls {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.search-input {
  width: 200px;
}

.section-tag {
  background: #e0f2fe;
  color: #0369a1;
  padding: 0.25rem 0.75rem;
  border-radius: 1rem;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
}

.field-name {
  font-weight: 500;
  color: #374151;
}

.field-value {
  color: #1f2937;
}

.value-text {
  font-weight: 500;
}

.empty-value {
  color: #9ca3af;
  font-style: italic;
}

.confidence-bar {
  width: 100%;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
}

.confidence-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.confidence-fill.high {
  background: #10b981;
}

.confidence-fill.medium {
  background: #f59e0b;
}

.confidence-fill.low {
  background: #ef4444;
}

.error-section {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
  background: #fef2f2;
  border-radius: 16px;
  margin-top: 2rem;
}

.error-content {
  text-align: center;
  padding: 2rem;
}

.error-content i {
  font-size: 3rem;
  color: #dc2626;
  margin-bottom: 1rem;
}

.error-content h3 {
  color: #dc2626;
  margin-bottom: 0.5rem;
}

.error-content p {
  color: #991b1b;
  margin-bottom: 2rem;
}

/* Utility classes */
.text-green-600 {
  color: #16a34a;
}

.text-red-600 {
  color: #dc2626;
}

/* PrimeVue overrides for compact table */
:deep(.compact-table .p-datatable-tbody > tr > td) {
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
}

:deep(.compact-table .p-datatable-thead > tr > th) {
  padding: 0.75rem;
  background: #1e293b;
  color: white;
  font-weight: 600;
  border: none;
}

:deep(.compact-table .p-datatable-tbody > tr:hover) {
  background: #f8fafc;
}

/* Responsive design */
@media (max-width: 768px) {
  .upload-header h2 {
    font-size: 1.5rem;
  }

  .drop-zone {
    padding: 2rem 1rem;
  }

  .upload-icon {
    font-size: 3rem;
  }

  .processing-steps {
    flex-direction: column;
    gap: 1rem;
  }

  .step {
    flex-direction: row;
    justify-content: flex-start;
    text-align: left;
    min-width: auto;
  }

  .results-header {
    flex-direction: column;
    align-items: stretch;
  }

  .action-buttons {
    justify-content: center;
  }

  .stats-row {
    gap: 1rem;
  }

  .stat-item {
    min-width: 100px;
    padding: 1rem;
  }

  .stat-number {
    font-size: 1.5rem;
  }

  .table-header {
    flex-direction: column;
    align-items: stretch;
  }

  .table-controls {
    justify-content: center;
  }

  .search-input {
    width: 100%;
  }
}

/* Animation for drag and drop */
@keyframes bounce {
  0%, 20%, 53%, 80%, 100% {
    transform: translate3d(0,0,0);
  }
  40%, 43% {
    transform: translate3d(0, -8px, 0);
  }
  70% {
    transform: translate3d(0, -4px, 0);
  }
  90% {
    transform: translate3d(0, -2px, 0);
  }
}

.drop-zone.drag-over .upload-icon {
  animation: bounce 1s ease infinite;
}
</style>
