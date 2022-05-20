<script setup lang="ts">
import Datepicker from "@vuepic/vue-datepicker";
import '@vuepic/vue-datepicker/dist/main.css';

import { inject } from "vue";
import type { MonitorsService } from "../../services";
import {dateUtil} from "../../utils";

const monitorsService = inject<MonitorsService>("MonitorsService")!;
const emit = defineEmits<{(e: "loadAll"): void}>();

function disabledDates(d: Date) {
  return d > dateUtil.dayjs().endOf("day").toDate();
}

function downloadCSV() {
  monitorsService.downloadCSV();
}

function loadAllEntries() {
  emit("loadAll");
}

</script>

<template>
 <div class="date-select columns is-mobile">
    <div class="column is-6">
      <div class="field">
        <label for="startDate" class="label is-small has-text-weight-normal">Date Range</label>
        <div class="control">
          <Datepicker v-model="monitorsService.dateRange" range :disabledDates="disabledDates" :enableTimePicker="false" autoApply />
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
        </div>
      </div>
    </div>
  </div>
</template>

