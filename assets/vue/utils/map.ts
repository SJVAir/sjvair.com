import { readableColor, darken } from "color2k";
import { Point } from "leaflet";
import { Monitor } from "../models";
import { dateUtil, pmValueToColor } from ".";

import type { Marker } from "leaflet";

export function genMarker(m: Monitor): Marker | undefined {
  // @ts-ignore: Property 'shapeMarker' does not exist on type Leaflet
  const marker = L.shapeMarker(m.data.position.coordinates.reverse(), {
    color: m.markerParams.border_color,
    weight: m.markerParams.border_size,
    fillColor: m.markerParams.fill_color,
    fillOpacity: 1,
    radius: m.markerParams.size,
    shape: m.markerParams.shape
  })

  marker.bindTooltip(`
    <div class="monitor-tooltip-container" style="background-color: ${ m.markerParams.fill_color }; color: ${ readableColor(m.markerParams.fill_color!) }">
      <p class="monitor-tooltip-date">${ dateUtil.$prettyPrint(m.data.latest.timestamp) }</p>
      <p class="is-size-4 is-underlined">${ m.data.name }</p>
      <div class="mt-1 is-flex is-justify-content-space-between is-align-items-flex-start is-flex-wrap-nowrap">
        <div class="monitor-tooltip-label is-flex is-justify-content-center is-align-items-center is-flex-direction-column mt-2 is-size-7">
          <p class="is-size-3">PM 2.5</p>
          <p class="is-size-8">(15 minute average)</p>
        </div>
        <p class="is-size-2 has-text-centered is-flex-grow-1">
          ${ Math.round(+m.data.latest[m.displayField]) }
        </p>
      </div>
    </div
  `, { offset: new Point(10, 0)});

  return marker;
}
