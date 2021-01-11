import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

dayjs.extend(utc);
dayjs.extend(timezone);

export default class GraphData {

  constructor(sensorFields) {
    if (!GraphData.instance) {
      console.log("creating new instance");
      Object.assign(this, GraphData.init(sensorFields));
      GraphData.instance = this;
    } else {
      console.log("reusing instance");
      return GraphData.instance;
    }
  }

  static from(sensorFields) {
    delete GraphData.instance;
    return new GraphData(sensorFields);
  }

  static init(sensorFields) {
    // The series apexcharts will bind to
    // Type: Array<Dataset>
    const data = [];

    // The names of the datasets in the series
    const datasetFields = Object.keys(sensorFields);

    // Create datasets for each specified sensor field
    const datasets = datasetFields.reduce((datasets, fieldName) => {
      // Create dataset
      datasets[fieldName] = [];

      // Add dataset reference to data series
      data.push({
        name: fieldName,
        data: datasets[fieldName]
      });

      return datasets;
    }, {});


    return {
      data,
      datasetFields,
      datasets,
      // Timestamp store to ensure entries are unique
      timestamps: new Set()
    };
  }

  addData(newData) {
    if (newData.length < 1) {
      // Do nothing if empty
      return;
    }

    for (let data of newData) {
      // Only process new entries
      if (!this.timestamps.has(data.timestamp)) {
        // Cache current data timestamp
        this.timestamps.add(data.timestamp);

        // Add data for each expected dataset
        for (let name of this.datasetFields) {
          this.datasets[name].push({
            x: dayjs.utc(data.timestamp).tz('America/Los_Angeles'),
            y: data[name]
          });
        }
      }
    }
  }
}
