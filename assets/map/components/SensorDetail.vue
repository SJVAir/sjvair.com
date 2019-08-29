<template>
<div class="sensor-detail">
  {{ sensor.name }}
</div>
</template>

<script>
export default {
  name: 'sensor-detail',
  props: {
    sensor: Object
  },
  methods: {
  }
}
</script>
