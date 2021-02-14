<template>
  <div id="chartContainer"></div>
</template>

<script>
import ChartController from "../../controllers/Chart.controller";
export default {
  name: "monitor-chart",

  props: [ "dataFields" ],

  data() {
    return {
      ctx: ChartController
    }
  },

  mounted() {
  },
}
</script>
