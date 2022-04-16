import { createApp, reactive} from "vue";
import { createRouter, createWebHashHistory } from "vue-router";
import App from "./App.vue";
import { Monitor } from "./models";
import MonitorDetail from "./components/MonitorDetail";
import { D3ServiceMono, MonitorsServiceMono } from "./services";

const d3Service = reactive(new D3ServiceMono());
const monitorService = reactive(new MonitorsServiceMono());
const monitorVisibility = reactive(Monitor.visibility);

const router = createRouter({
  history: createWebHashHistory(),
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
app.provide<typeof monitorVisibility>("MonitorVisibility", monitorVisibility);
app.mount("#app");
