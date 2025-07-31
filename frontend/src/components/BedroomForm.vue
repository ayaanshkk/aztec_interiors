<template>
  <div class="bedroom-form-container">
    <PrimeToast />

    <div class="form-header">
      <h2>BEDROOM CHECKLIST</h2>
      <div class="header-actions">
        <PrimeButton
          label="Generate PDF"
          icon="pi pi-file-pdf"
          @click="generatePDF"
          class="p-button-success"
          :loading="pdfLoading"
        />
        <PrimeButton
          label="Generate Excel"
          icon="pi pi-file-excel"
          @click="generateExcel"
          class="p-button-info"
          :loading="excelLoading"
        />
        <PrimeButton
          label="Clear Form"
          icon="pi pi-refresh"
          @click="clearForm"
          class="p-button-secondary"
        />
      </div>
    </div>

    <form @submit.prevent="generatePDF" class="bedroom-form">
      <!-- Customer Information Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Customer Information</h3>
        </div>
        <div class="form-grid">
          <div class="form-group">
            <label>Customer Name</label>
            <InputText v-model="formData.customer_name" placeholder="Enter customer name" />
          </div>
          <div class="form-group">
            <label>Survey Date</label>
            <PrimeCalendar v-model="formData.survey_date" dateFormat="dd/mm/yy" />
          </div>
          <div class="form-group">
            <label>Address</label>
            <InputText v-model="formData.address" placeholder="Enter address" />
          </div>
          <div class="form-group">
            <label>Appt Date</label>
            <PrimeCalendar v-model="formData.appt_date" dateFormat="dd/mm/yy" />
          </div>
          <div class="form-group">
            <label>Room</label>
            <InputText v-model="formData.room" placeholder="Enter room" />
          </div>
          <div class="form-group">
            <label>Pro Inst Date</label>
            <PrimeCalendar v-model="formData.pro_inst_date" dateFormat="dd/mm/yy" />
          </div>
          <div class="form-group">
            <label>Tel/Mob Number</label>
            <InputText v-model="formData.tel_mob_number" placeholder="Enter phone number" />
          </div>
          <div class="form-group">
            <label>Comp Chk Date</label>
            <PrimeCalendar v-model="formData.comp_chk_date" dateFormat="dd/mm/yy" />
          </div>
          <div class="form-group">
            <label></label>
            <div></div>
          </div>
          <div class="form-group">
            <label>Date Deposit Paid</label>
            <PrimeCalendar v-model="formData.date_deposit_paid" dateFormat="dd/mm/yy" />
          </div>
        </div>
      </div>

      <!-- Style and Colors Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Style & Colors</h3>
        </div>
        <div class="form-grid">
          <div class="form-group">
            <label>Fitting Style</label>
            <InputText v-model="formData.fitting_style" placeholder="e.g., Modern" />
          </div>
          <div class="form-group">
            <label>Door Style</label>
            <InputText v-model="formData.door_style" placeholder="e.g., Wooden" />
          </div>
          <div class="form-group">
            <label>Door Colour</label>
            <InputText v-model="formData.door_colour" placeholder="e.g., Brown" />
          </div>
          <div class="form-group">
            <label>End Panel Colour</label>
            <InputText v-model="formData.end_panel_colour" placeholder="e.g., White" />
          </div>
          <div class="form-group">
            <label>Plinth/Filler Colour</label>
            <InputText v-model="formData.plinth_filler_colour" placeholder="e.g., Black" />
          </div>
          <div class="form-group">
            <label>Worktop Colour</label>
            <InputText v-model="formData.worktop_colour" placeholder="e.g., White" />
          </div>
          <div class="form-group">
            <label>Cabinet Colour</label>
            <InputText v-model="formData.cabinet_colour" placeholder="e.g., White" />
          </div>
          <div class="form-group">
            <label>Handles Code/Qty/Size</label>
            <InputText v-model="formData.handles_code_qty_size" placeholder="Enter handle details" />
          </div>
        </div>
      </div>

      <!-- Bedside Cabinets Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Bedside Cabinets</h3>
        </div>
        <div class="checkbox-grid">
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.bedside_cabinets_floating" binary />
            <label>Floating</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.bedside_cabinets_fitted" binary />
            <label>Fitted</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.bedside_cabinets_freestand" binary />
            <label>Freestand</label>
          </div>
          <div class="form-group">
            <label>Qty</label>
            <InputNumber v-model="formData.bedside_cabinets_qty" :min="0" />
          </div>
        </div>
      </div>

      <!-- Dresser/Desk Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Dresser / Desk</h3>
        </div>
        <div class="checkbox-grid">
          <div class="checkbox-group">
            <RadioButton v-model="formData.dresser_desk_option" inputId="dresser_yes" value="yes" />
            <label for="dresser_yes">Yes</label>
          </div>
          <div class="checkbox-group">
            <RadioButton v-model="formData.dresser_desk_option" inputId="dresser_no" value="no" />
            <label for="dresser_no">No</label>
          </div>
          <div class="form-group">
            <label>Qty/Size</label>
            <InputText v-model="formData.dresser_desk_qty_size" placeholder="Enter quantity/size" />
          </div>
        </div>
      </div>

      <!-- Internal Mirror Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Internal Mirror</h3>
        </div>
        <div class="checkbox-grid">
          <div class="checkbox-group">
            <RadioButton v-model="formData.internal_mirror_option" inputId="mirror_yes" value="yes" />
            <label for="mirror_yes">Yes</label>
          </div>
          <div class="checkbox-group">
            <RadioButton v-model="formData.internal_mirror_option" inputId="mirror_no" value="no" />
            <label for="mirror_no">No</label>
          </div>
          <div class="form-group">
            <label>Qty/Size</label>
            <InputText v-model="formData.internal_mirror_qty_size" placeholder="Enter quantity/size" />
          </div>
        </div>
      </div>

      <!-- Mirror Options Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Mirror</h3>
        </div>
        <div class="checkbox-grid">
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.mirror_silver" binary />
            <label>Silver</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.mirror_bronze" binary />
            <label>Bronze</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.mirror_grey" binary />
            <label>Grey</label>
          </div>
          <div class="form-group">
            <label>Qty</label>
            <InputNumber v-model="formData.mirror_qty" :min="0" />
          </div>
        </div>
      </div>

      <!-- Soffit Lights Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Soffit Lights</h3>
        </div>
        <div class="checkbox-grid">
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.soffit_lights_spot" binary />
            <label>Spot</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.soffit_lights_strip" binary />
            <label>Strip</label>
          </div>
          <div class="form-group">
            <label>Colour</label>
            <InputText v-model="formData.soffit_lights_colour" placeholder="Enter colour" />
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.soffit_lights_cool_white" binary />
            <label>Cool White</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.soffit_lights_warm_white" binary />
            <label>Warm White</label>
          </div>
          <div class="form-group">
            <label>Qty</label>
            <InputNumber v-model="formData.soffit_lights_qty" :min="0" />
          </div>
        </div>
      </div>

      <!-- Gable Lights Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Gable Lights</h3>
        </div>
        <div class="checkbox-grid">
          <div class="form-group">
            <label>Colour</label>
            <InputText v-model="formData.gable_lights_colour" placeholder="Enter colour" />
          </div>
          <div class="form-group">
            <label>Profile Colour</label>
            <InputText v-model="formData.gable_lights_profile_colour" placeholder="Enter profile colour" />
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.gable_lights_black" binary />
            <label>Black</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.gable_lights_white" binary />
            <label>White</label>
          </div>
          <div class="form-group">
            <label>Qty</label>
            <InputNumber v-model="formData.gable_lights_qty" :min="0" />
          </div>
        </div>
      </div>

      <!-- Other/Misc/Accessories Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Other / Misc / Accessories</h3>
        </div>
        <div class="checkbox-grid">
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.carpet_protection" binary />
            <label>Carpet Protection</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.floor_tile_protection" binary />
            <label>Floor Tile Protection</label>
          </div>
          <div class="checkbox-group">
            <PrimeCheckbox v-model="formData.no_floor" binary />
            <label>No Floor</label>
          </div>
        </div>
      </div>

      <!-- Terms and Signature Section -->
      <div class="form-section">
        <div class="section-header">
          <h3>Terms & Signature</h3>
        </div>
        <div class="form-grid">
          <div class="form-group">
            <label>Date Terms & Conditions Given</label>
            <PrimeCalendar v-model="formData.date_terms_conditions_given" dateFormat="dd/mm/yy" />
          </div>
          <div class="form-group">
            <label>Gas & Electric Installation Terms Given</label>
            <PrimeCalendar v-model="formData.gas_electric_installation_terms_given" dateFormat="dd/mm/yy" />
          </div>
          <div class="form-group">
            <label>Customer Signature</label>
            <InputText v-model="formData.customer_signature" placeholder="Customer signature" />
          </div>
          <div class="form-group">
            <label>Signature Date</label>
            <PrimeCalendar v-model="formData.signature_date" dateFormat="dd/mm/yy" />
          </div>
        </div>
      </div>
    </form>

    <!-- Download Links -->
    <div v-if="downloadLinks.pdf || downloadLinks.excel" class="download-section">
      <h3>Downloads</h3>
      <div class="download-buttons">
        <PrimeButton
          v-if="downloadLinks.pdf"
          label="Download PDF"
          icon="pi pi-download"
          @click="downloadFile(downloadLinks.pdf)"
          class="p-button-success"
        />
        <PrimeButton
          v-if="downloadLinks.excel"
          label="Download Excel"
          icon="pi pi-download"
          @click="downloadFile(downloadLinks.excel)"
          class="p-button-info"
        />
      </div>
    </div>
  </div>
</template>

<script>
import InputText from 'primevue/inputtext';
import InputNumber from 'primevue/inputnumber';
import Calendar from 'primevue/calendar';
import Checkbox from 'primevue/checkbox';
import RadioButton from 'primevue/radiobutton';
import PrimeButton from 'primevue/button';
import Toast from 'primevue/toast';

export default {
  name: 'BedroomForm',
  components: {
    InputText,
    InputNumber,
    PrimeCalendar: Calendar,
    PrimeCheckbox: Checkbox,
    RadioButton,
    PrimeButton,
    PrimeToast: Toast
  },
  data() {
    return {
      pdfLoading: false,
      excelLoading: false,
      downloadLinks: {
        pdf: null,
        excel: null
      },
      formData: {
        // Customer Information
        customer_name: '',
        address: '',
        room: '',
        tel_mob_number: '',
        survey_date: null,
        appt_date: null,
        pro_inst_date: null,
        comp_chk_date: null,
        date_deposit_paid: null,

        // Style and Color
        fitting_style: '',
        door_style: '',
        door_colour: '',
        end_panel_colour: '',
        plinth_filler_colour: '',
        worktop_colour: '',
        cabinet_colour: '',
        handles_code_qty_size: '',

        // Bedside Cabinets
        bedside_cabinets_floating: false,
        bedside_cabinets_fitted: false,
        bedside_cabinets_freestand: false,
        bedside_cabinets_qty: 0,

        // Dresser/Desk
        dresser_desk_option: null,
        dresser_desk_qty_size: '',

        // Internal Mirror
        internal_mirror_option: null,
        internal_mirror_qty_size: '',

        // Mirror
        mirror_silver: false,
        mirror_bronze: false,
        mirror_grey: false,
        mirror_qty: 0,

        // Soffit Lights
        soffit_lights_spot: false,
        soffit_lights_strip: false,
        soffit_lights_colour: '',
        soffit_lights_cool_white: false,
        soffit_lights_warm_white: false,
        soffit_lights_qty: 0,

        // Gable Lights
        gable_lights_colour: '',
        gable_lights_profile_colour: '',
        gable_lights_black: false,
        gable_lights_white: false,
        gable_lights_qty: 0,

        // Other/Misc/Accessories
        carpet_protection: false,
        floor_tile_protection: false,
        no_floor: false,

        // Terms and Signature
        date_terms_conditions_given: null,
        gas_electric_installation_terms_given: null,
        customer_signature: '',
        signature_date: null
      }
    };
  },
  methods: {
    async generatePDF() {
      this.pdfLoading = true;
      try {
        const processedData = this.processFormData();

        console.log('Sending PDF request to:', 'http://localhost:5000/generate-pdf');
        console.log('Data:', processedData);

        const response = await fetch('http://localhost:5000/generate-pdf', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ data: processedData })
        });

        console.log('Response status:', response.status);
        const result = await response.json();
        console.log('Response data:', result);

        if (result.success) {
          this.downloadLinks.pdf = `http://localhost:5000${result.pdf_download_url}`;
          this.$toast.add({
            severity: 'success',
            summary: 'Success',
            detail: 'PDF generated successfully!',
            life: 3000
          });
        } else {
          throw new Error(result.error || 'PDF generation failed');
        }
      } catch (error) {
        console.error('PDF generation error:', error);
        let errorMessage = 'Failed to generate PDF';

        if (error.name === 'TypeError' && error.message.includes('fetch')) {
          errorMessage = 'Cannot connect to server. Please make sure the backend is running on http://localhost:5000';
        } else {
          errorMessage = error.message || 'Unknown error occurred';
        }

        this.$toast.add({
          severity: 'error',
          summary: 'Error',
          detail: errorMessage,
          life: 4000
        });
      } finally {
        this.pdfLoading = false;
      }
    },

    async generateExcel() {
      this.excelLoading = true;
      try {
        const processedData = this.processFormData();

        console.log('Sending Excel request to:', 'http://localhost:5000/generate-excel');
        console.log('Data:', processedData);

        const response = await fetch('http://localhost:5000/generate-excel', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ data: processedData })
        });

        console.log('Response status:', response.status);
        const result = await response.json();
        console.log('Response data:', result);

        if (result.success) {
          this.downloadLinks.excel = `http://localhost:5000${result.excel_download_url}`;
          this.$toast.add({
            severity: 'success',
            summary: 'Success',
            detail: 'Excel file generated successfully!',
            life: 3000
          });
        } else {
          throw new Error(result.error || 'Excel generation failed');
        }
      } catch (error) {
        console.error('Excel generation error:', error);
        let errorMessage = 'Failed to generate Excel';

        if (error.name === 'TypeError' && error.message.includes('fetch')) {
          errorMessage = 'Cannot connect to server. Please make sure the backend is running on http://localhost:5000';
        } else {
          errorMessage = error.message || 'Unknown error occurred';
        }

        this.$toast.add({
          severity: 'error',
          summary: 'Error',
          detail: errorMessage,
          life: 4000
        });
      } finally {
        this.excelLoading = false;
      }
    },

    processFormData() {
      const processed = { ...this.formData };

      // Convert dates to strings
      Object.keys(processed).forEach(key => {
        if (processed[key] instanceof Date) {
          processed[key] = processed[key].toLocaleDateString('en-GB');
        }
      });

      // Process radio button options
      processed.dresser_desk_yes = processed.dresser_desk_option === 'yes';
      processed.dresser_desk_no = processed.dresser_desk_option === 'no';
      processed.internal_mirror_yes = processed.internal_mirror_option === 'yes';
      processed.internal_mirror_no = processed.internal_mirror_option === 'no';

      // Remove the temporary option fields
      delete processed.dresser_desk_option;
      delete processed.internal_mirror_option;

      return processed;
    },

    clearForm() {
      this.formData = {
        // Customer Information
        customer_name: '',
        address: '',
        room: '',
        tel_mob_number: '',
        survey_date: null,
        appt_date: null,
        pro_inst_date: null,
        comp_chk_date: null,
        date_deposit_paid: null,

        // Style and Color
        fitting_style: '',
        door_style: '',
        door_colour: '',
        end_panel_colour: '',
        plinth_filler_colour: '',
        worktop_colour: '',
        cabinet_colour: '',
        handles_code_qty_size: '',

        // Bedside Cabinets
        bedside_cabinets_floating: false,
        bedside_cabinets_fitted: false,
        bedside_cabinets_freestand: false,
        bedside_cabinets_qty: 0,

        // Dresser/Desk
        dresser_desk_option: null,
        dresser_desk_qty_size: '',

        // Internal Mirror
        internal_mirror_option: null,
        internal_mirror_qty_size: '',

        // Mirror
        mirror_silver: false,
        mirror_bronze: false,
        mirror_grey: false,
        mirror_qty: 0,

        // Soffit Lights
        soffit_lights_spot: false,
        soffit_lights_strip: false,
        soffit_lights_colour: '',
        soffit_lights_cool_white: false,
        soffit_lights_warm_white: false,
        soffit_lights_qty: 0,

        // Gable Lights
        gable_lights_colour: '',
        gable_lights_profile_colour: '',
        gable_lights_black: false,
        gable_lights_white: false,
        gable_lights_qty: 0,

        // Other/Misc/Accessories
        carpet_protection: false,
        floor_tile_protection: false,
        no_floor: false,

        // Terms and Signature
        date_terms_conditions_given: null,
        gas_electric_installation_terms_given: null,
        customer_signature: '',
        signature_date: null
      };

      this.downloadLinks = { pdf: null, excel: null };

      this.$toast.add({
        severity: 'info',
        summary: 'Form Cleared',
        detail: 'All form data has been reset',
        life: 2000
      });
    },

    downloadFile(url) {
      window.open(url, '_blank');
    }
  }
};
</script>

<style scoped>
.bedroom-form-container {
  max-width: 1200px;
  margin: 0 auto;
}

.form-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  padding: 1.5rem;
  background: linear-gradient(135deg, #1e293b, #334155);
  color: white;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.form-header h2 {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: 1px;
}

.header-actions {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.bedroom-form {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.form-section {
  background: linear-gradient(135deg, #ffffff, #f8fafc);
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transition: box-shadow 0.2s ease;
}

.form-section:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.section-header {
  margin-bottom: 1.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 2px solid #e2e8f0;
}

.section-header h3 {
  margin: 0;
  color: #1e293b;
  font-size: 1.25rem;
  font-weight: 600;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.25rem;
  align-items: start;
}

.checkbox-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.25rem;
  align-items: center;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  font-weight: 600;
  color: #374151;
  font-size: 0.9rem;
}

.checkbox-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.checkbox-group:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.checkbox-group label {
  margin: 0;
  cursor: pointer;
  font-weight: 500;
  color: #475569;
}

.download-section {
  margin-top: 2rem;
  padding: 1.5rem;
  background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
  border: 1px solid #bae6fd;
  border-radius: 12px;
  text-align: center;
}

.download-section h3 {
  margin-top: 0;
  margin-bottom: 1rem;
  color: #0c4a6e;
  font-weight: 600;
}

.download-buttons {
  display: flex;
  gap: 1rem;
  justify-content: center;
  flex-wrap: wrap;
}

/* PrimeVue component overrides */
:deep(.p-inputtext) {
  border-radius: 8px;
  border: 1px solid #d1d5db;
  padding: 0.75rem;
  transition: all 0.2s ease;
  background-color: #ffffff;
  color: #374151;
}

:deep(.p-inputtext:focus) {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  background-color: #ffffff;
}

:deep(.p-calendar) {
  width: 100%;
}

:deep(.p-calendar .p-inputtext) {
  width: 100%;
  background-color: #ffffff;
  color: #374151;
}

:deep(.p-inputnumber-input) {
  border-radius: 8px;
  border: 1px solid #d1d5db;
  padding: 0.75rem;
  background-color: #ffffff;
  color: #374151;
}

:deep(.p-checkbox .p-checkbox-box) {
  border-radius: 6px;
  width: 1.25rem;
  height: 1.25rem;
  background-color: #ffffff;
}

:deep(.p-radiobutton .p-radiobutton-box) {
  width: 1.25rem;
  height: 1.25rem;
  background-color: #ffffff;
}

/* Responsive design */
@media (max-width: 768px) {
  .form-header {
    flex-direction: column;
    gap: 1rem;
    text-align: center;
  }

  .header-actions {
    justify-content: center;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .checkbox-grid {
    grid-template-columns: 1fr;
  }

  .download-buttons {
    flex-direction: column;
    align-items: center;
  }
}
</style>
