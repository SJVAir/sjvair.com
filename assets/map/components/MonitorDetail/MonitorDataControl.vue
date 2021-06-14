<template>
  <div class="date-select columns is-mobile">
    <div class="column is-3">
      <div class="field">
        <label for="startDate" class="label is-small has-text-weight-normal">Start Date</label>
        <div class="control">
          <datepicker id="startDate" format="yyyy-MM-dd" :disabled-dates="{customPredictor: checkStartDate}" input-class="input is-small" typeable placeholder="Start Date" v-model="startDate"></datepicker>
        </div>
      </div>
    </div>
    <div class="column is-3">
      <div class="field">
        <label for="endDate" class="label is-small has-text-weight-normal">End Date</label>
        <div class="control">
          <datepicker id="endDate" format="yyyy-MM-dd" :disabled-dates="{customPredictor: checkEndDate}" input-class="input is-small" typeable placeholder="End Date" v-model="endDate"></datepicker>
        </div>
      </div>
    </div>
    <div class="column is-6">
      <div class="field is-grouped">
        <div class="control">
          <br />
          <button class="button is-small is-info" v-on:click="loadAllEntries">
            <span class="icon is-small">
              <span :class="{ 'fa-spin': loading }" class="fal fa-redo"></span>
            </span>
            <span>Update</span>
          </button>
        </div>
        <div class="control">
          <br />
          <button class="button is-small is-success" v-on:click="downloadCSV">
            <span class="icon is-small">
              <span class="fal fa-download"></span>
            </span>
            <span>Download</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import Datepicker from 'vuejs-datepicker/dist/vuejs-datepicker.esm.js';
import monitorsService from '../../services/Monitors.service';

export default {
  name: "monitor-data-control",
  components: {
    Datepicker
  },
  data() {
    const updateURL = () => {
      this.$router.push({
        name: "details",
        params: {
          id: monitorsService.activeMonitor.id
        },
        query: {
          timestamp__gte: monitorsService.activeMonitor.dateRange.gte,
          timestamp__lte: monitorsService.activeMonitor.dateRange.lte
        }
      });
    };

    return {
      ctx: monitorsService,
      get startDate() {
        return this.ctx.activeMonitor.dateRange.gte;
      },
      set startDate(timestamp) {
        this.ctx.activeMonitor.dateRange.gte = timestamp;
        updateURL();
      },
      get endDate() {
        return this.ctx.activeMonitor.dateRange.lte;
      },
      set endDate(timestamp) {
        this.ctx.activeMonitor.dateRange.lte = timestamp;
        updateURL();
      },
    }
  },
  methods: {
    checkStartDate(date) {
      // Date must be lte endDate and lte today.
      // true means disabled.
      const gteEnd = date > this.$date(this.endDate).endOf('day').toDate();
      const gteTonight = date > this.$date().endOf('day').toDate();
      return gteEnd || gteTonight;
    },
    checkEndDate(date) {
      // Date must be gte startDate and lte today.
      // true means disabled.
      const lteStart = date < this.$date(this.startDate).startOf('day').toDate();
      const gteTonight = date > this.$date().endOf('day').toDate();
      return lteStart || gteTonight;
    },
    downloadCSV() {
      this.monitor.downloadCSV();
    },
    loadAllEntries() {
      this.$emit("loadAll");
    }
  }
}
</script>
