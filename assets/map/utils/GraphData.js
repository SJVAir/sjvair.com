import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

dayjs.extend(utc);
dayjs.extend(timezone);

export default class GraphData {

  constructor(sensorFields) {
    // The series apexcharts will bind to
    // Type: Array<Dataset>
    this.data = [];

    // The names of the datasets in the series
    this.datasetFields = Object.keys(sensorFields);

    // Quick references to specific datasets in the data series
    this.data = [];
    this.dataRefs = this.datasetFields.reduce((dataRefs, fieldName) => {
      // Create dataset for each field
      dataRefs[fieldName] = [];

      // Add field reference to data series
      this.data.push({
        name: fieldName,
        data: dataRefs[fieldName]
      });

      return dataRefs;
    }, {});


    // Timestamp store to ensure entries are unique
    this.timestampSet = new Set();
  }

  addData(newData) {
    if (newData.length < 1) {
      // Do nothing if empty
      return;
    }

    for (let data of newData) {
      // Only process new entries
      if (!this.timestampSet.has(data.timestamp)) {
        // Cache current data timestamp
        this.timestampSet.add(data.timestamp);

        // Add data for each expected dataset
        for (let name of this.datasetFields) {
          this.dataRefs[name].push({
            x: dayjs.utc(data.timestamp).tz('America/Los_Angeles'),
            y: data[name]
          });
        }
      }
    }
  }
}
