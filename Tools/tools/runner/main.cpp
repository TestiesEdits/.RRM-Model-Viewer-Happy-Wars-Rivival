#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>
#include <algorithm>

namespace fs = std::filesystem;

// Platform-specific clear screen
void clear_screen() {
#ifdef _WIN32
    std::system("cls");
#else
    std::system("clear");
#endif
}

struct Args {
    std::string mode = "to-obj";      // "to-obj" or "to-rrm"
    fs::path input = "Input";
    fs::path output = "Output";
    bool interactive = false;
};

fs::path find_script_path() {
    std::vector<fs::path> candidates = {
        fs::path("tools") / "rrm_converter.py",
        fs::path("..") / "rrm_converter.py",
        fs::path("rrm_converter.py"),
        fs::current_path() / "tools" / "rrm_converter.py"
    };
    
    for (const auto& p : candidates) {
        if (fs::exists(p)) return p;
    }
    return "";
}

int run_batch(const Args& args) {
    if (!fs::exists(args.input) || !fs::is_directory(args.input)) {
        std::cerr << "Input directory does not exist: " << args.input << "\n";
        return 1;
    }
    fs::create_directories(args.output);

    fs::path script = find_script_path();
    if (script.empty()) {
        std::cerr << "Missing converter script (rrm_converter.py)\n";
        return 1;
    }

    int failures = 0;
    int processed = 0;

    std::cout << "\nStarting conversion: " << args.mode << "\n";
    std::cout << "Input: " << args.input << "\n";
    std::cout << "Output: " << args.output << "\n";
    std::cout << "----------------------------------------\n";

    if (args.mode == "to-obj") {
        for (const auto& entry : fs::directory_iterator(args.input)) {
            if (entry.is_regular_file() && entry.path().extension() == ".rrm") {
                fs::path p = entry.path();
                fs::path stem = p.stem();
                fs::path out_obj = args.output / (stem.string() + ".obj");
                
                std::string cmd = "python \"" + script.string() + "\" autoextract \"" + p.string() + "\" \"" + out_obj.string() + "\"";
                std::cout << "[RRM->OBJ] " << p.filename().string() << " -> " << out_obj.filename().string() << "\n";
                
                int rc = std::system(cmd.c_str());
                if (rc != 0) {
                    std::cerr << "  FAILED (rc=" << rc << ")\n";
                    ++failures;
                } else {
                    processed++;
                }
            }
        }
    } else if (args.mode == "to-rrm") {
        for (const auto& entry : fs::directory_iterator(args.input)) {
            if (entry.is_regular_file() && entry.path().extension() == ".obj") {
                fs::path p = entry.path();
                fs::path stem = p.stem();
                fs::path out_rrm = args.output / (stem.string() + ".rrm");
                
                std::string cmd = "python \"" + script.string() + "\" obj2rrm \"" + p.string() + "\" \"" + out_rrm.string() + "\"";
                std::cout << "[OBJ->RRM] " << p.filename().string() << " -> " << out_rrm.filename().string() << "\n";
                
                int rc = std::system(cmd.c_str());
                if (rc != 0) {
                    std::cerr << "  FAILED (rc=" << rc << ")\n";
                    ++failures;
                } else {
                    processed++;
                }
            }
        }
    }

    std::cout << "----------------------------------------\n";
    if (failures > 0) {
        std::cerr << "Completed with " << failures << " failures. Processed: " << processed << "\n";
        return 1;
    }
    std::cout << "Success! Processed " << processed << " files.\n";
    return 0;
}

void print_toggle(bool to_obj) {
    std::cout << "   _______________________ \n";
    std::cout << "  |                       |\n";
    if (to_obj) {
        std::cout << "  |  [ ON ]  RRM -> OBJ   |\n";
        std::cout << "  |  [    ]  OBJ -> RRM   |\n";
    } else {
        std::cout << "  |  [    ]  RRM -> OBJ   |\n";
        std::cout << "  |  [ ON ]  OBJ -> RRM   |\n";
    }
    std::cout << "  |_______________________|\n";
}

void interactive_mode(Args& args) {
    bool running = true;
    while (running) {
        clear_screen();
        std::cout << "=========================================\n";
        std::cout << "          RRM CONVERTER TOOL             \n";
        std::cout << "=========================================\n\n";
        
        print_toggle(args.mode == "to-obj");
        
        std::cout << "\n";
        std::cout << "  Input Folder:  " << args.input.string() << "\n";
        std::cout << "  Output Folder: " << args.output.string() << "\n";
        std::cout << "\n=========================================\n";
        std::cout << " [T]oggle Mode\n";
        std::cout << " [S]et Folders\n";
        std::cout << " [R]un Conversion\n";
        std::cout << " [Q]uit\n";
        std::cout << "-----------------------------------------\n";
        std::cout << "> ";

        std::string line;
        std::getline(std::cin, line);
        if (line.empty()) continue;
        
        char choice = std::toupper(line[0]);

        if (choice == 'Q') {
            running = false;
        } else if (choice == 'T') {
            args.mode = (args.mode == "to-obj") ? "to-rrm" : "to-obj";
        } else if (choice == 'S') {
            std::cout << "Enter Input Folder path: ";
            std::string in_str;
            std::getline(std::cin, in_str);
            if (!in_str.empty()) args.input = in_str;
            
            std::cout << "Enter Output Folder path: ";
            std::string out_str;
            std::getline(std::cin, out_str);
            if (!out_str.empty()) args.output = out_str;
        } else if (choice == 'R') {
            run_batch(args);
            std::cout << "\nPress Enter to continue...";
            std::cin.ignore();
            std::cin.get();
        }
    }
}

int main(int argc, char** argv) {
    Args args;
    
    // Check if arguments are provided
    if (argc > 1) {
        // Parse args
         for (int i = 1; i < argc; ++i) {
            std::string a = argv[i];
            if (a == "--mode" && i + 1 < argc) {
                args.mode = argv[++i];
            } else if (a == "--input" && i + 1 < argc) {
                args.input = argv[++i];
            } else if (a == "--output" && i + 1 < argc) {
                args.output = argv[++i];
            } else {
                std::cout << "Unknown argument: " << a << "\n";
                return 1;
            }
        }
        return run_batch(args);
    } else {
        // Default interactive mode
        interactive_mode(args);
    }

    return 0;
}
