# Antiquarian viz playground — feel-test three viz stacks side-by-side.
#
# Usage:
#   make all PROJECT=itguy                    # build all three stacks for itguy
#   make all PROJECT=itguy REPO=/path/to/itguy
#   make all PROJECT=comictagger REPO=/tmp/comictagger
#   make data PROJECT=itguy                   # just regen the JSON
#   make observable PROJECT=itguy             # build the Observable Framework variant
#   make vega-lite PROJECT=itguy              # build the Vega-Lite static harness
#   make svg PROJECT=itguy                    # build the hand-rolled SVG variant
#   make serve PROJECT=itguy                  # serve output/<project>/ on localhost:8765
#   make clean PROJECT=itguy                  # remove output/<project>/

PROJECT ?= itguy
REPO ?= $(if $(filter itguy,$(PROJECT)),/Users/tom/Documents/work/itguy,$(if $(filter comictagger,$(PROJECT)),/tmp/comictagger,$(error REPO is required for PROJECT=$(PROJECT))))

OUT := output/$(PROJECT)
DATA := $(OUT)/data
PORT ?= 8765

PYTHON := uv run python

.PHONY: all data observable vega-lite svg index serve clean print-config

all: data observable vega-lite svg index
	@echo
	@echo "Built all three stacks for PROJECT=$(PROJECT). Open these side-by-side:"
	@echo "  - $(OUT)/observable/index.html"
	@echo "  - $(OUT)/vega-lite-static/index.html"
	@echo "  - $(OUT)/hand-svg/index.html"
	@echo
	@echo "Or run \`make serve PROJECT=$(PROJECT)\` to view via http://localhost:$(PORT)."

index:
	$(PYTHON) data/landing.py --project $(PROJECT) --output-dir $(OUT)


print-config:
	@echo "PROJECT=$(PROJECT)"
	@echo "REPO=$(REPO)"
	@echo "OUT=$(OUT)"

data: $(DATA)/manifest.json

# Re-extract whenever the script changes OR the repo's cache.db changes.
$(DATA)/manifest.json: data/extract.py $(REPO)/.antiquarian/cache.db
	@mkdir -p $(DATA)
	$(PYTHON) data/extract.py --project $(PROJECT) --repo $(REPO)

observable: data
	$(PYTHON) observable/build.py --project $(PROJECT) --data-dir $(DATA) --output-dir $(OUT)/observable

vega-lite: data
	$(PYTHON) vega-lite-static/build.py --project $(PROJECT) --data-dir $(DATA) --output-dir $(OUT)/vega-lite-static

svg: data
	$(PYTHON) hand-svg/build.py --project $(PROJECT) --data-dir $(DATA) --output-dir $(OUT)/hand-svg

serve:
	@echo "Serving $(OUT) at http://localhost:$(PORT)/ (Ctrl-C to stop)"
	@cd $(OUT) && $(PYTHON) -m http.server $(PORT)

clean:
	rm -rf $(OUT)
