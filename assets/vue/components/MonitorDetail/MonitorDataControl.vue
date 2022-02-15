<script setup lang="ts">
import Datepicker from "vue3-date-time-picker";
import "vue3-date-time-picker/dist/main.css"
import MonitorSubscription from "../MonitorSubscription.vue";

import { defineEmits, inject, ref, watch } from "vue";
import { useRouter } from "vue-router";
import type { MonitorsService } from "../../services";

const monitorsService = inject<MonitorsService>("MonitorsService")!;
const dateRange = ref([monitorsService.dateRange.start.toDate(), monitorsService.dateRange.end.toDate()]);
const emit = defineEmits<{(e: "loadAll"): void}>();
const router = useRouter();


function updateURL() {
  router.push({
    name: "details",
    params: {
      id: monitorsService.activeMonitor!.data.id
    },
    query: {
      timestamp__gte: monitorsService.dateRange.start.toISOString(),
      timestamp__lte: monitorsService.dateRange.end.toISOString()
    }
  });
};

//function checkStartDate(date: Date) {
//  // Date must be lte endDate and lte today.
//  // true means disabled.
//  const gteEnd = date > MonitorsService.dateRange.end.toDate();
//  const gteTonight = date > dateUtil.dayjs().endOf('day').toDate();
//  return gteEnd || gteTonight;
//}
//
//function checkEndDate(date) {
//  // Date must be gte startDate and lte today.
//  // true means disabled.
//  const lteStart = date < dateUtil(startDate).startOf('day').toDate();
//  const gteTonight = date > dateUtil().endOf('day').toDate();
//  return lteStart || gteTonight;
//}

function downloadCSV() {
  monitorsService.downloadCSV();
}

function loadAllEntries() {
  emit("loadAll");
}

watch(
  () => dateRange,
  () => updateURL()
);

//export default {
//  name: "monitor-data-control",
//  components: {
//    Datepicker,
//    MonitorSubscription
//  },
//  data() {
//    const updateURL = () => {
//      this.$router.push({
//        name: "details",
//        params: {
//          id: monitorsService.activeMonitor.id
//        },
//        query: {
//          timestamp__gte: monitorsService.activeMonitor.dateRange.gte,
//          timestamp__lte: monitorsService.activeMonitor.dateRange.lte
//        }
//      });
//    };
//
//    return {
//      ctx: monitorsService,
//      get startDate() {
//        return this.ctx.activeMonitor.dateRange.gte;
//      },
//      set startDate(timestamp) {
//        this.ctx.activeMonitor.dateRange.gte = timestamp;
//        updateURL();
//      },
//      get endDate() {
//        return this.ctx.activeMonitor.dateRange.lte;
//      },
//      set endDate(timestamp) {
//        this.ctx.activeMonitor.dateRange.lte = timestamp;
//        updateURL();
//      },
//    }
//  },
//  methods: {
//    checkStartDate(date) {
//      // Date must be lte endDate and lte today.
//      // true means disabled.
//      const gteEnd = date > this.$date(this.endDate).endOf('day').toDate();
//      const gteTonight = date > this.$date().endOf('day').toDate();
//      return gteEnd || gteTonight;
//    },
//    checkEndDate(date) {
//      // Date must be gte startDate and lte today.
//      // true means disabled.
//      const lteStart = date < this.$date(this.startDate).startOf('day').toDate();
//      const gteTonight = date > this.$date().endOf('day').toDate();
//      return lteStart || gteTonight;
//    },
//    downloadCSV() {
//      this.ctx.activeMonitor.downloadCSV();
//    },
//    loadAllEntries() {
//      this.$emit("loadAll");
//    }
//  }
//}
</script>

<template>
 <div class="date-select columns is-mobile">
    <div class="column is-6">
      <div class="field">
        <label for="startDate" class="label is-small has-text-weight-normal">Date Range</label>
        <div class="control">
          <Datepicker v-model="dateRange" range />
        </div>
      </div>
    </div>
    <div class="column is-6">
      <div class="field is-grouped">
        <div class="control">
          <br />
          <button class="button is-small is-info" v-on:click="loadAllEntries">
            <span class="icon is-small">
              <span :class="{ 'fa-spin': monitorsService.loadingEntries }" class="fal fa-redo"></span>
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
        <div class="control">
          <br />
          <monitor-subscription></monitor-subscription>
        </div>
      </div>
    </div>
  </div>
</template>

