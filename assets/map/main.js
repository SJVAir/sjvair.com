import Vue from 'vue'
import VueResource from 'vue-resource'
import App from './App.vue'

Vue.use(VueResource);

Vue.config.productionTip = false

new Vue({
  render: h => h(App),
}).$mount('#app')
