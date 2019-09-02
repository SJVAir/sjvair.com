import Vue from 'vue'
// import AsyncComputed from 'vue-async-computed'
import VueResource from 'vue-resource'
import App from './App.vue'

// Vue.use(AsyncComputed);
Vue.use(VueResource);

Vue.config.productionTip = false
Vue.http.options.root = '/api/1.0/';
// Vue.http.options.root = 'https://ccac-camp-api.herokuapp.com/api/1.0/';

new Vue({
  render: h => h(App),
}).$mount('#app')
