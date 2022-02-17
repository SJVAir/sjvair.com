import { createApp, reactive} from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import MonitorDetail from "./components/MonitorDetail";
import { D3Service, MonitorsService } from "./services";

const monitorService = reactive(new MonitorsService());
const d3Service = reactive(new D3Service());

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/monitor/:id',
      name: 'details',
      component: MonitorDetail,
      props: true,
    }
  ]
});

const app = createApp(App);

app.use(router);
app.provide<typeof d3Service>("D3Service", d3Service);
app.provide<typeof monitorService>("MonitorsService", monitorService);
app.mount("#app");
