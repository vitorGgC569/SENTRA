module sentra.local/hcsbridge

go 1.26.8

require github.com/Microsoft/hcsshim v0.0.0

// Build from this directory against the separately pinned source clone.
// No build or dependency resolution is performed by the executor.
replace github.com/Microsoft/hcsshim => ../../third_party/hcsshim
