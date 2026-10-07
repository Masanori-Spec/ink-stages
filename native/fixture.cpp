#include <cairo-pdf.h>
#include <gtk/gtk.h>
#include <clocale>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "control/xojfile/LoadHandler.h"
#include "control/xojfile/SaveHandler.h"
#include "model/Document.h"
#include "model/DocumentHandler.h"
#include "model/Font.h"
#include "model/Layer.h"
#include "model/Point.h"
#include "model/Stroke.h"
#include "model/Text.h"
#include "model/XojPage.h"
#include "util/Color.h"
#include "util/PathUtil.h"

namespace f = std::filesystem;

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

// Synthetic background generation only. All XOPP rendering uses the official
// release AppImage, never this fixture author or a replacement renderer.
void background(const f::path& path) {
    require(!f::exists(path), "Background must be fresh");
    auto* surface = cairo_pdf_surface_create(path.c_str(), 360, 240);
    auto* cr = cairo_create(surface);
    for (int i = 0; i < 2; ++i) {
        const double w = i == 0 ? 360 : 240;
        const double h = i == 0 ? 240 : 360;
        cairo_pdf_surface_set_size(surface, w, h);
        cairo_set_source_rgb(cr, 247.0 / 255.0, 237.0 / 255.0, 211.0 / 255.0);
        cairo_paint(cr);
        cairo_set_source_rgb(cr, 0, 0, 0);
        cairo_select_font_face(cr, "DejaVu Sans", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(cr, 10);
        cairo_move_to(cr, 15, h - 15);
        cairo_show_text(cr, i == 0 ? "BACKGROUND_ONE" : "BACKGROUND_TWO");
        cairo_show_page(cr);
    }
    require(cairo_status(cr) == CAIRO_STATUS_SUCCESS, "Background Cairo error");
    cairo_destroy(cr);
    cairo_surface_finish(surface);
    require(cairo_surface_status(surface) == CAIRO_STATUS_SUCCESS, "Background PDF write error");
    cairo_surface_destroy(surface);
}

void art(Layer* layer, const std::string& label, Color color,
         double x, double y, double w, double h) {
    auto text = std::make_unique<Text>();
    text->setFont(XojFont("DejaVu Sans", 16));
    text->setText(label);
    text->setX(x);
    text->setY(y - 25);
    text->setColor(color);
    layer->addElement(std::move(text));
    auto shape = std::make_unique<Stroke>();
    shape->setToolType(StrokeTool::PEN);
    shape->setColor(color);
    shape->setWidth(2);
    shape->setFill(255);
    for (const auto& point : std::vector<Point>{{x, y}, {x + w, y}, {x + w, y + h}, {x, y + h}, {x, y}}) {
        shape->addPoint(point);
    }
    layer->addElement(std::move(shape));
}

void save(Document& doc, const f::path& path) {
    require(!f::exists(path), "Native save path must be fresh");
    SaveHandler writer;
    writer.prepareSave(&doc, path);
    require(writer.getErrorMessage().empty(), writer.getErrorMessage());
    writer.saveTo(path);
    require(writer.getErrorMessage().empty(), writer.getErrorMessage());
    require(f::is_regular_file(path) && f::file_size(path) > 0, "Native save produced no file");
}

std::unique_ptr<Document> load(const f::path& path) {
    LoadHandler reader;
    auto doc = reader.loadDocument(path);
    require(doc != nullptr, reader.getLastError());
    require(reader.getMissingPdfFilename().empty(), "Native resource missing");
    require(!reader.isAttachedPdfMissing(), "Native attachment missing");
    return doc;
}

void snapshot(const Document& doc, const f::path& path) {
    require(!f::exists(path), "Snapshot must be fresh");
    std::ofstream out(path);
    std::set<const Layer*> owners;
    out << "{\"pages\":[";
    for (size_t pi = 0; pi < doc.getPageCount(); ++pi) {
        if (pi) out << ',';
        auto page = doc.getPage(pi);
        require(page->getSelectedLayerId() >= 1 && page->getSelectedLayerId() <= page->getLayerCount(),
                "Selected native layer is out of bounds");
        out << "{\"width\":" << page->getWidth() << ",\"height\":" << page->getHeight()
            << ",\"pdfPage\":" << page->getPdfPageNr() + 1 << ",\"layers\":[";
        size_t li = 0;
        for (const auto* layer : page->getLayersView()) {
            require(owners.insert(layer).second, "A native Layer has multiple owners");
            if (li++) out << ',';
            out << "{\"name\":" << std::quoted(layer->getName()) << ",\"elements\":[";
            size_t ei = 0;
            for (const auto* element : layer->getElementsView()) {
                if (ei++) out << ',';
                auto color = element->getColor();
                out << "{\"rgb\":[" << unsigned(color.red) << ',' << unsigned(color.green) << ','
                    << unsigned(color.blue) << ']';
                if (const auto* text = dynamic_cast<const Text*>(element)) {
                    out << ",\"text\":" << std::quoted(text->getText())
                        << ",\"x\":" << text->getX() << ",\"y\":" << text->getY();
                } else if (const auto* stroke = dynamic_cast<const Stroke*>(element)) {
                    out << ",\"points\":[";
                    size_t i = 0;
                    for (const auto& p : stroke->getPointVector()) {
                        if (i++) out << ',';
                        out << '[' << p.x << ',' << p.y << ']';
                    }
                    out << "],\"fill\":" << stroke->getFill();
                } else {
                    throw std::runtime_error("Unexpected fixture element");
                }
                out << '}';
            }
            out << "]}";
        }
        out << "]}";
    }
    out << "]}\n";
    require(bool(out), "Snapshot write failed");
}

int main(int argc, char** argv) {
    try {
        require(argc == 2, "Usage: inkstages-fixture NEW_OUTPUT_DIRECTORY");
        f::path dir = f::absolute(argv[1]);
        require(!f::exists(dir), "Fixture directory must be fresh");
        f::create_directories(dir);
        gtk_init(nullptr, nullptr);
        std::setlocale(LC_NUMERIC, "C");
        background(dir / "background.pdf");

        DocumentHandler handler;
        Document doc(&handler);
        const bool imported = doc.readPdf(dir / "background.pdf", true, false);
        require(imported, "Native PDF import failed: " + doc.getLastErrorMsg());
        require(doc.getPageCount() == 2, "Native PDF import did not create two pages");
        doc.setFilepath(dir / "original.xopp");
        doc.setPathStorageMode(Util::PathStorageMode::AS_RELATIVE_PATH);
        auto one = doc.getPage(0);
        auto two = doc.getPage(1);
        require(one->getLayerCount() == 1 && two->getLayerCount() == 1, "Unexpected native starting layers");
        auto* a = one->getLayers().front();
        a->setName("A");
        art(a, "ALPHA", Color(220, 30, 40), 30, 60, 60, 50);
        // API-only model construction. This public collection owns Layer pointers;
        // there are no GUI listeners requiring LayerController notifications.
        auto* b = new Layer(); b->setName("B"); one->getLayers().push_back(b);
        art(b, "BRAVO", Color(30, 170, 60), 70, 90, 90, 50);
        auto* c = new Layer(); c->setName("C"); one->getLayers().push_back(c);
        art(c, "CHARLIE", Color(40, 80, 220), 200, 60, 70, 50);
        auto* d = two->getLayers().front(); d->setName("D");
        art(d, "DELTA", Color(135, 55, 175), 60, 80, 80, 80);
        one->setSelectedLayerId(1); two->setSelectedLayerId(1);
        snapshot(doc, dir / "authored.json");
        save(doc, dir / "original.xopp");

        auto reopened = load(dir / "original.xopp");
        snapshot(*reopened, dir / "reopened.json");
        save(*reopened, dir / "native-resaved.xopp");
        auto fresh = load(dir / "native-resaved.xopp");
        snapshot(*fresh, dir / "resaved-reopened.json");

        auto inserted = load(dir / "original.xopp");
        auto page = inserted->getPage(0);
        auto* unrelated = new Layer(); unrelated->setName("UNUSED");
        art(unrelated, "UNUSED", Color(220, 30, 190), 280, 150, 50, 50);
        page->getLayers().insert(page->getLayers().begin() + 1, unrelated);
        page->setSelectedLayerId(1);
        save(*inserted, dir / "inserted.xopp");
        auto insertedRead = load(dir / "inserted.xopp");
        snapshot(*insertedRead, dir / "inserted-reopened.json");

        auto duplicate = load(dir / "original.xopp");
        duplicate->getPage(0)->getLayers()[1]->setName("A");
        save(*duplicate, dir / "duplicate.xopp");
        auto missing = load(dir / "original.xopp");
        missing->getPage(0)->getLayers()[2]->setName("C-renamed");
        save(*missing, dir / "missing.xopp");
        std::cout << "Official API author/save/load/resave/reopen and inserted/invalid fixtures complete\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
