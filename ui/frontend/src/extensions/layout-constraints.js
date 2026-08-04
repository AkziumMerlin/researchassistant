const LAYOUT_CONSTRAINTS_MARK = "researchAssistantLayoutConstraintsV1";

if (!globalThis[LAYOUT_CONSTRAINTS_MARK]) {
  globalThis[LAYOUT_CONSTRAINTS_MARK] = true;
  installLayoutConstraints();
}

function installLayoutConstraints() {
  if (document.getElementById("ra-layout-constraints")) return;
  const style = document.createElement("style");
  style.id = "ra-layout-constraints";
  style.textContent = `
    /* Models has six vertical regions. The previous five-row grid assigned
       the growing component palette to an implicit auto row, so it expanded
       beyond the dialog instead of creating a scroll container. */
    .ra-models-main {
      min-height: 0 !important;
      overflow: hidden !important;
      grid-template-rows: auto auto auto auto minmax(0, 1fr) auto !important;
    }
    .ra-models-work {
      min-height: 0 !important;
      overflow: hidden !important;
    }
    .raComponentSearchPalette {
      box-sizing: border-box;
      min-height: 0 !important;
      height: 100% !important;
      max-height: none !important;
      overflow: hidden !important;
      grid-template-rows: auto auto minmax(0, 1fr) !important;
    }
    .raComponentSearchScroll {
      display: grid !important;
      grid-template-rows: minmax(0, 1fr) !important;
      min-height: 0 !important;
      height: 100% !important;
      max-height: 100% !important;
      overflow: hidden !important;
    }
    .raComponentSearchScroll > #ra-palette-list,
    .raComponentSearchScroll > .raComponentSearchResults {
      box-sizing: border-box;
      min-height: 0 !important;
      height: 100% !important;
      max-height: none !important;
      overflow-x: hidden !important;
      overflow-y: scroll !important;
      overscroll-behavior: contain;
      scrollbar-gutter: stable;
      scrollbar-width: auto;
      scrollbar-color: #6f9482 #0b1210;
    }
    .raComponentSearchScroll > #ra-palette-list::-webkit-scrollbar,
    .raComponentSearchScroll > .raComponentSearchResults::-webkit-scrollbar {
      width: 12px;
    }
    .raComponentSearchScroll > #ra-palette-list::-webkit-scrollbar-track,
    .raComponentSearchScroll > .raComponentSearchResults::-webkit-scrollbar-track {
      background: #0b1210;
      border-left: 1px solid #2d4037;
    }
    .raComponentSearchScroll > #ra-palette-list::-webkit-scrollbar-thumb,
    .raComponentSearchScroll > .raComponentSearchResults::-webkit-scrollbar-thumb {
      min-height: 30px;
      border: 2px solid #0b1210;
      border-radius: 999px;
      background: #6f9482;
    }

    /* Research workspace header and tabs have variable heights. A fixed
       calc(100% - 112px) overflows as soon as tabs wrap or fonts differ. */
    .rwDialog[open] {
      display: grid !important;
      grid-template-rows: auto auto minmax(0, 1fr) !important;
      overflow: hidden !important;
    }
    .rwMain {
      box-sizing: border-box;
      min-height: 0 !important;
      height: auto !important;
      max-height: none !important;
      overflow-x: hidden !important;
      overflow-y: auto !important;
      overscroll-behavior: contain;
      scrollbar-gutter: stable;
    }
  `;
  document.head.append(style);
}
