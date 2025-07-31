import { createApp } from 'vue';
import App from './App.vue';
import PrimeVue from 'primevue/config';
import Lara from '@primevue/themes/lara';

// Import PrimeVue components
import FileUpload from 'primevue/fileupload';
import Button from 'primevue/button';
import ProgressSpinner from 'primevue/progressspinner';
import ToastService from 'primevue/toastservice';
import Toast from 'primevue/toast';
import InputText from 'primevue/inputtext';
import InputNumber from 'primevue/inputnumber';
import Calendar from 'primevue/calendar';
import Checkbox from 'primevue/checkbox';
import RadioButton from 'primevue/radiobutton';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';

import 'primeicons/primeicons.css';

const app = createApp(App);

app.use(PrimeVue, {
    theme: {
        preset: Lara,
        options: {
            prefix: 'p',
            darkModeSelector: 'system',
            cssLayer: false
        }
    }
});

app.use(ToastService);

// Register components globally
app.component('FileUpload', FileUpload);
app.component('PrimeButton', Button);
app.component('ProgressSpinner', ProgressSpinner);
app.component('PrimeToast', Toast);
app.component('InputText', InputText);
app.component('InputNumber', InputNumber);
app.component('PrimeCalendar', Calendar);
app.component('PrimeCheckbox', Checkbox);
app.component('RadioButton', RadioButton);
app.component('DataTable', DataTable);
app.component('PrimeColumn', Column);

app.mount('#app');
