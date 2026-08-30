// @ts-check
/**
 * One shared parser/builder config for OOXML. Read and write must agree on
 * attribute prefixing and text-node naming or a round-trip will silently
 * corrupt content — so both docx/read-docx.js and docx/write-docx.js import
 * from here instead of each declaring their own options.
 */
import { XMLParser, XMLBuilder } from 'fast-xml-parser';

export const XML_OPTIONS = {
  ignoreAttributes: false,
  attributeNamePrefix: '@_',
  textNodeName: '#text',
  preserveOrder: false,
  trimValues: false,
};

export const xmlParser = new XMLParser(XML_OPTIONS);

export const xmlBuilder = new XMLBuilder({
  ...XML_OPTIONS,
  suppressEmptyNode: true,
  format: false,
});

/**
 * Order-preserving builder, used only by write-docx.js's table-aware path
 * (see xml-order.js for why preserveOrder:true is needed there but not for
 * the simpler paragraph-only path).
 */
export const xmlBuilderOrdered = new XMLBuilder({
  ...XML_OPTIONS,
  preserveOrder: true,
  suppressEmptyNode: true,
  format: false,
});

export const XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n';
