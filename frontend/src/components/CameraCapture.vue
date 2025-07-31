<template>
  <div class="camera-capture-container">
    <PrimeToast />

    <!-- Back Button -->
    <div class="header-actions mb-4">
      <PrimeButton
        label="Back to Dashboard"
        icon="pi pi-arrow-left"
        @click="$emit('back')"
        class="p-button-secondary"
      />
    </div>

    <!-- Camera Interface -->
    <div v-if="!processingComplete" class="camera-interface">
      <div class="camera-header">
        <h2><i class="pi pi-camera mr-2"></i>Take Photo of Form</h2>
        <p>Position your bedroom checklist form in the camera frame and take a photo for instant processing</p>
      </div>

      <!-- Camera View -->
      <div class="camera-container">
        <div v-if="!cameraActive" class="camera-placeholder">
          <div class="placeholder-content">
            <i class="pi pi-camera camera-icon"></i>
            <h3>Ready to Capture</h3>
            <p>Click "Start Camera" to begin</p>
            <PrimeButton
              label="Start Camera"
              icon="pi pi-video"
              @click="startCamera"
              class="p-button-primary p-button-lg"
              :disabled="loading"
            />
          </div>
        </div>

        <div v-else class="camera-active">
          <video
            ref="videoElement"
            autoplay
            playsinline
            class="camera-video"
          ></video>

          <div class="camera-overlay">
            <div class="frame-guide">
              <div class="corner top-left"></div>
              <div class="corner top-right"></div>
              <div class="corner bottom-left"></div>
              <div class="corner bottom-right"></div>
              <div class="guide-text">Position form within frame</div>
            </div>
          </div>

          <div class="camera-controls">
            <PrimeButton
              label="Stop Camera"
              icon="pi pi-times"
              @click="stopCamera"
              class="p-button-secondary"
              :disabled="loading"
            />
            <PrimeButton
              label="Capture & Process"
              icon="pi pi-camera"
              @click="capturePhoto"
              class="p-button-success p-button-lg capture-btn"
              :loading="loading"
            />
            <PrimeButton
              label="Upload Instead"
              icon="pi pi-upload"
              @click="showFileUpload = true"
              class="p-button-info"
              :disabled="loading"
            />
          </div>
        </div>

        <!-- File Upload Alternative -->
        <div v-if="showFileUpload" class="file-upload-section">
          <h4>Or Upload an Image</h4>
          <FileUpload
            name="image"
            mode="basic"
            accept="image/*"
            :auto="false"
            @select="onFileSelect"
            chooseLabel="Choose Image File"
            class="w-full"
            :disabled="loading"
          />
        </div>
      </div>

      <!-- Processing Status -->
      <div v-if="loading" class="processing-status">
        <ProgressSpinner
          style="width: 60px; height: 60px"
          strokeWidth="4"
          fill="var(--surface-ground)"
          animationDuration="1s"
          aria-label="Processing"
        />
        <h3>Processing Image...</h3>
        <p>{{ processingMessage }}</p>
        <div class="processing-steps">
          <div class="step" :class="{ active: currentStep >= 1, complete: currentStep > 1 }">
            <i class="pi pi-eye"></i>
            <span>Analyzing Image</span>
          </div>
          <div class="step" :class="{ active: currentStep >= 2, complete: currentStep > 2 }">
            <i class="pi pi-cog"></i>
            <span>Extracting Data</span>
          </div>
          <div class="step" :class="{ active: currentStep >= 3, complete: currentStep > 3 }">
            <i class="pi pi-file"></i>
            <span>Generating Files</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Results Display -->
    <div v-if="processingComplete && extractedData" class="results-section">
      <div class="results-header">
        <h2><i class="pi pi-check-circle mr-2 text-green-500"></i>Processing Complete!</h2>
        <div class="header-actions">
          <PrimeButton
            label="Process Another"
            icon="pi pi-camera"
            @click="resetCapture"
            class="p-button-primary"
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

      <!-- Data Table -->
      <div class="data-table-container">
        <DataTable
          :value="formattedData"
          class="p-datatable-sm"
          :paginator="true"
          :rows="15"
          :rowsPerPageOptions="[15, 25, 50]"
          responsiveLayout="scroll"
          filterDisplay="menu"
          :globalFilterFields="['section', 'field', 'value']"
        >
          <template #header>
            <div class="flex justify-content-between align-items-center">
              <h5 class="m-0">Extracted Form Data</h5>
              <span class="p-input-icon-left">
                <i class="pi pi-search" />
                <InputText v-model="globalFilter" placeholder="Search..." />
              </span>
            </div>
          </template>

          <Column field="section" header="Section" :sortable="true" style="min-width: 150px">
            <template #body="{ data }">
              <span v-if="data.section" class="section-badge">{{ data.section }}</span>
            </template>
          </Column>

          <Column field="field" header="Field" :sortable="true" style="min-width: 200px">
            <template #body="{ data }">
              <span class="field-name">{{ data.field }}</span>
            </template>
          </Column>

          <Column field="value" header="Value" :sortable="true" style="min-width: 200px">
            <template #body="{ data }">
              <span v-if="data.value" class="field-value">
                <i v-if="data.value === '✓'" class="pi pi-check text-green-500 font-bold text-lg"></i>
                <i v-else-if="data.value === '✗'" class="pi pi-times text-red-500 font-bold text-lg"></i>
                <span v-else>{{ data.value }}</span>
              </span>
              <span v-else class="text-gray-400 italic">Not specified</span>
            </template>
          </Column>

          <Column field="notes" header="Notes" style="min-width: 150px">
            <template #body="{ data }">
              <InputText
                v-model="data.notes"
                placeholder="Add notes..."
                class="w-full p-inputtext-sm"
              />
            </template>
          </Column>
        </DataTable>
      </div>
    </div>

    <!-- Error Display -->
    <div v-if="error" class="error-section">
      <div class="error-content">
        <i class="pi pi-exclamation-triangle error-icon"></i>
        <h3>Processing Failed</h3>
        <p>{{ error }}</p>
        <div class="error-actions">
          <PrimeButton
            label="Try Again"
            icon="pi pi-refresh"
            @click="resetCapture"
            class="p-button-primary"
          />
          <PrimeButton
            label="Upload File Instead"
            icon="pi pi-upload"
            @click="showFileUpload = true; error = null"
            class="p-button-secondary"
          />
        </div>
      </div>
    </div>

    <!-- Hidden canvas for photo capture -->
    <canvas ref="canvasElement" style="display: none;"></canvas>
  </div>
</template>

<script>
export default {
  name: 'CameraCapture',
  emits: ['back', 'data-processed'],
  data() {
    return {
      cameraActive: false,
      loading: false,
      processingComplete: false,
      showFileUpload: false,
      error: null,
      extractedData: null,
      pdfUrl: null,
      excelUrl: null,
      globalFilter: null,
      currentStep: 0,
      processingMessage: 'Starting processing...',
      stream: null
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
            notes: ''
          });
        }
      }

      return formattedData;
    }
  },
  methods: {
    async startCamera() {
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 1280 },
            height: { ideal: 720 },
            facingMode: 'environment' // Use back camera on mobile
          }
        });
        this.$refs.videoElement.srcObject = this.stream;
        this.cameraActive = true;

        this.$toast.add({
          severity: 'success',
          summary: 'Camera Started',
          detail: 'Position your form in the frame and capture',
          life: 3000
        });
      } catch (error) {
        console.error('Camera access error:', error);
        this.error = 'Could not access camera. Please check permissions or use file upload.';
        this.showFileUpload = true;
      }
    },

    stopCamera() {
      if (this.stream) {
        this.stream.getTracks().forEach(track => track.stop());
        this.stream = null;
      }
      this.cameraActive = false;
    },

    async capturePhoto() {
      if (!this.cameraActive || !this.$refs.videoElement) return;

      this.loading = true;
      this.currentStep = 1;
      this.processingMessage = 'Capturing image...';

      try {
        const video = this.$refs.videoElement;
        const canvas = this.$refs.canvasElement;
        const context = canvas.getContext('2d');

        // Set canvas dimensions to match video
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        // Draw the video frame to canvas
        context.drawImage(video, 0, 0, canvas.width, canvas.height);

        // Convert to blob
        canvas.toBlob(async (blob) => {
          const file = new File([blob], 'captured-form.jpg', { type: 'image/jpeg' });
          await this.processImage(file);
        }, 'image/jpeg', 0.9);

        // Stop camera after capture
        this.stopCamera();

      } catch (error) {
        console.error('Capture error:', error);
        this.error = 'Failed to capture photo. Please try again.';
        this.loading = false;
        this.currentStep = 0;
      }
    },

    onFileSelect(event) {
      const file = event.files[0];
      if (file) {
        this.processImage(file);
      }
    },

    async processImage(file) {
      this.loading = true;
      this.currentStep = 1;
      this.processingMessage = 'Analyzing image with AI...';
      this.error = null;

      try {
        const formData = new FormData();
        formData.append('image', file);

        // Step 2: Extract data
        this.currentStep = 2;
        this.processingMessage = 'Extracting form data...';

        const response = await fetch('http://localhost:5000/upload', {
          method: 'POST',
          body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.error || `Server error: ${response.status}`);
        }

        if (data.success) {
          // Step 3: Generate files
          this.currentStep = 3;
          this.processingMessage = 'Generating PDF and Excel files...';

          this.extractedData = data.structured_data;
          this.pdfUrl = `http://localhost:5000${data.pdf_download_url}`;
          this.excelUrl = `http://localhost:5000${data.excel_download_url}`;

          // Complete processing
          const processingStartTime = Date.now();
          setTimeout(() => {
            this.loading = false;
            this.processingComplete = true;
            this.currentStep = 0;

            // Emit the processed data to parent
            this.$emit('data-processed', {
              data: this.extractedData,
              pdfUrl: this.pdfUrl,
              excelUrl: this.excelUrl,
              processingTime: ((Date.now() - processingStartTime) / 1000).toFixed(1)
            });

            this.$toast.add({
              severity: 'success',
              summary: 'Processing Complete!',
              detail: 'Form data extracted and files generated successfully',
              life: 4000
            });
          }, 500);

        } else {
          throw new Error(data.error || 'Processing failed');
        }

      } catch (error) {
        console.error('Processing error:', error);
        this.error = error.message || 'Failed to process image';
        this.loading = false;
        this.currentStep = 0;

        this.$toast.add({
          severity: 'error',
          summary: 'Processing Failed',
          detail: this.error,
          life: 4000
        });
      }
    },

    resetCapture() {
      this.processingComplete = false;
      this.extractedData = null;
      this.pdfUrl = null;
      this.excelUrl = null;
      this.error = null;
      this.showFileUpload = false;
      this.loading = false;
      this.currentStep = 0;
    },

    downloadFile(url) {
      if (url) {
        window.open(url, '_blank');
      }
    }
  },

  beforeUnmount() {
    this.stopCamera();
  }
};
</script>

<style scoped>
.camera-capture-container {
  max-width: 1200px;
  margin: 0 auto;
}

.camera-interface {
  text-align: center;
}

.camera-header {
  margin-bottom: 2rem;
}

.camera-header h2 {
  color: #1e293b;
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.camera-header p {
  color: #64748b;
  font-size: 1.125rem;
}

.camera-container {
  position: relative;
  max-width: 800px;
  margin: 0 auto;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.camera-placeholder {
  background: linear-gradient(135deg, #f8fafc, #e2e8f0);
  padding: 4rem 2rem;
  min-height: 400px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-content {
  text-align: center;
}

.camera-icon {
  font-size: 4rem;
  color: #64748b;
  margin-bottom: 1rem;
}

.camera-active {
  position: relative;
}

.camera-video {
  width: 100%;
  height: auto;
  max-height: 500px;
  object-fit: cover;
}

.camera-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
}

.frame-guide {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 80%;
  height: 70%;
  border: 3px dashed rgba(59, 130, 246, 0.8);
  border-radius: 12px;
}

.corner {
  position: absolute;
  width: 30px;
  height: 30px;
  border: 4px solid #3b82f6;
}

.corner.top-left {
  top: -15px;
  left: -15px;
  border-right: none;
  border-bottom: none;
  border-radius: 8px 0 0 0;
}

.corner.top-right {
  top: -15px;
  right: -15px;
  border-left: none;
  border-bottom: none;
  border-radius: 0 8px 0 0;
}

.corner.bottom-right {
  bottom: -15px;
  right: -15px;
  border-left: none;
  border-top: none;
  border-radius: 0 0 8px 0;
}

.guide-text {
  position: absolute;
  top: -50px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(59, 130, 246, 0.9);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  font-size: 0.875rem;
  font-weight: 600;
  white-space: nowrap;
}

.camera-controls {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 1rem;
  align-items: center;
  background: rgba(0, 0, 0, 0.7);
  padding: 1rem;
  border-radius: 50px;
  backdrop-filter: blur(10px);
}

.capture-btn {
  font-size: 1.1rem;
  padding: 1rem 2rem;
}

.file-upload-section {
  margin-top: 2rem;
  padding: 2rem;
  background: #f8fafc;
  border-radius: 12px;
  border: 2px dashed #cbd5e1;
}

.processing-status {
  text-align: center;
  padding: 3rem 2rem;
}

.processing-status h3 {
  color: #1e293b;
  margin: 1rem 0 0.5rem 0;
}

.processing-status p {
  color: #64748b;
  font-size: 1.125rem;
  margin-bottom: 2rem;
}

.processing-steps {
  display: flex;
  justify-content: center;
  gap: 2rem;
  margin-top: 2rem;
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
  min-width: 120px;
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
  text-align: center;
}

.results-section {
  margin-top: 2rem;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 2rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.results-header h2 {
  color: #1e293b;
  font-size: 1.75rem;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.data-table-container {
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.section-badge {
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  color: white;
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

.error-section {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
  background: #fef2f2;
  border-radius: 16px;
  margin-top: 2rem;
}

.error-content {
  text-align: center;
  padding: 2rem;
}

.error-icon {
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

.error-actions {
  display: flex;
  gap: 1rem;
  justify-content: center;
  flex-wrap: wrap;
}

/* Utility classes */
.text-green-500 {
  color: #10b981;
}

.text-red-500 {
  color: #ef4444;
}

.text-gray-400 {
  color: #9ca3af;
}

.text-lg {
  font-size: 1.125rem;
}

/* PrimeVue DataTable customizations */
:deep(.p-datatable .p-datatable-header) {
  background: linear-gradient(135deg, #f8fafc, #e2e8f0);
  border-bottom: 2px solid #e2e8f0;
  padding: 1rem;
}

:deep(.p-datatable .p-datatable-thead > tr > th) {
  background: linear-gradient(135deg, #1e293b, #334155);
  color: white;
  font-weight: 600;
  padding: 1rem;
  border: none;
}

:deep(.p-datatable .p-datatable-tbody > tr > td) {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #f1f5f9;
}

:deep(.p-datatable .p-datatable-tbody > tr:hover) {
  background: #f8fafc;
}

:deep(.p-paginator) {
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  padding: 1rem;
}

/* Responsive design */
@media (max-width: 768px) {
  .camera-header h2 {
    font-size: 1.5rem;
  }

  .camera-header p {
    font-size: 1rem;
  }

  .camera-controls {
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem;
    bottom: 10px;
  }

  .capture-btn {
    font-size: 1rem;
    padding: 0.75rem 1.5rem;
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

  .header-actions {
    justify-content: center;
  }

  .error-actions {
    flex-direction: column;
    align-items: center;
  }

  :deep(.p-datatable .p-datatable-thead > tr > th),
  :deep(.p-datatable .p-datatable-tbody > tr > td) {
    padding: 0.5rem;
    font-size: 0.875rem;
  }
}

/* Camera frame animations */
.frame-guide {
  animation: pulse-frame 2s ease-in-out infinite;
}

@keyframes pulse-frame {
  0%, 100% {
    border-color: rgba(59, 130, 246, 0.8);
  }
  50% {
    border-color: rgba(59, 130, 246, 0.4);
  }
}

.corner {
  animation: corner-glow 2s ease-in-out infinite;
}

@keyframes corner-glow {
  0%, 100% {
    border-color: #3b82f6;
    box-shadow: 0 0 0 rgba(59, 130, 246, 0);
  }
  50% {
    border-color: #60a5fa;
    box-shadow: 0 0 10px rgba(59, 130, 246, 0.3);
  }
}
</style>left {
  bottom: -15px;
  left: -15px;
  border-right: none;
  border-top: none;
  border-radius: 0 0 0 8px;
}

.corner.bottom-
