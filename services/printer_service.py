from __future__ import annotations


class PrinterService:
    def list_printers(self) -> list[dict[str, str]]:
        try:
            import win32print
        except ImportError as exc:
            raise RuntimeError("pywin32 is required to read Windows printers") from exc

        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        printers = win32print.EnumPrinters(flags, None, 2)
        names = sorted({printer["pPrinterName"] for printer in printers if printer.get("pPrinterName")})
        return [{"name": name} for name in names]

    def printer_exists(self, printer_name: str) -> bool:
        if not printer_name:
            return False
        return any(item["name"] == printer_name for item in self.list_printers())

