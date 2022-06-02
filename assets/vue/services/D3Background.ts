import { dateUtil } from "../modules/date";
import { BackgroundService } from "../webworkers/BackgroundService";

let last_active_limit: any = null;
let prevDataPoint: any = null;

export const D3BackgroundService = {
  updateLastActiveLimit(limit: any) {
    last_active_limit = limit;
    return last_active_limit;
  },

  /**
   * Helper function to compute the contiguous segments of the data
   *
   * Derived from https://github.com/pbeshai/d3-line-chunked/blob/master/src/lineChunked.js
   *
   * @param {Array} data the line data
   * @param {Function} isNext function that takes the previous data point and the
   *    current one and returns true if the current point is the expected one to
   *    follow the previous, false otherwise.
   * @return {Array} An array of segments (subarrays) of the line data
  */
  computeSegments(data: Array<any>, isNext?: (prev: any, curr: any) => boolean): { gaps: Array<any>, segments: any } {
    isNext = isNext || function () { return true; };
    let startNewSegment = true;

    // split into segments of continuous data
    let segments = data.reduce((segments, d) => {
      // skip if this point has no data
      if (!this.lineDefined(d)) {
        startNewSegment = true;
        return segments;
      }

      // if we are starting a new segment, start it with this point
      if (startNewSegment) {
        segments.push([d]);
        startNewSegment = false;

      // otherwise see if we are adding to the last segment
      } else {
        const lastSegment = segments[segments.length - 1];
        const lastDatum = lastSegment[lastSegment.length - 1];
        // if we expect this point to come next, add it to the segment
        if (isNext!(lastDatum, d)) {
          lastSegment.push(d);

        // otherwise create a new segment
        } else {
          segments.push([d]);
        }
      }

      return segments;
    }, []);

    const gaps = data.filter(this.lineDefined);
    return { gaps, segments };
  },

  // Calculate if there should be a line between 2 given points
  lineDefined(dataPoint: any) {

    if (!prevDataPoint) {
      prevDataPoint = dataPoint;
      return true;
    }

    const deltaRaw = dateUtil.dayjs(prevDataPoint.xData).diff(dateUtil.dayjs(dataPoint.xData));
    const deltaAsSec = Math.ceil(deltaRaw / 1000);

    prevDataPoint = dataPoint;
    return deltaAsSec < last_active_limit;
  }
}

export default new BackgroundService(D3BackgroundService);
