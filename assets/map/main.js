import Vue from 'vue';
import VueRouter from 'vue-router';
import App from './App.vue';
import MonitorDetail from './components/MonitorDetail';
import dateUtil from './utils/date';
import http from './utils/http';

Vue.prototype.$date = dateUtil;
Vue.prototype.$http = http;

const routes = [
  {
    path: '/monitor/:id',
    name: 'details',
    component: MonitorDetail,
    props: true,
    alias: '/monitor/:id/?timestamp__gte=:timestamp__gte&timestamp__lte=:timestamp__lte'
  }
];

const router = new VueRouter({ routes });

new Vue({
  router,
  render: h => h(App),
}).$mount('#app')

