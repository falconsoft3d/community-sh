#!/bin/bash

# Community SH - Automatic Backup Cron Job Installer
# This script helps you install the cron job for automatic backups

echo "=========================================="
echo "Community SH - Backup Cron Job Installer"
echo "=========================================="
echo ""

# Get the current directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
LOG_FILE="/var/log/community_sh_backups.log"

echo "Project directory: $PROJECT_DIR"
echo "Python executable: $VENV_PYTHON"
echo "Log file: $LOG_FILE"
echo ""

# Check if virtual environment exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ Error: Virtual environment not found at $VENV_PYTHON"
    exit 1
fi

# Create log directory if it doesn't exist
echo "Creating log directory..."
sudo mkdir -p /var/log
sudo touch $LOG_FILE
sudo chmod 666 $LOG_FILE

# Show current crontab
echo ""
echo "Current crontab entries:"
crontab -l 2>/dev/null || echo "(No crontab entries)"
echo ""

# Ask user for frequency
echo "Select backup check frequency:"
echo "1) Every 5 minutes (recommended for 'minutes' frequency)"
echo "2) Every hour (recommended for 'hourly' frequency)"
echo "3) Every day at midnight (recommended for 'daily' frequency)"
echo "4) Every week on Monday at midnight (recommended for 'weekly' frequency)"
echo ""
read -p "Enter your choice (1-4): " choice

case $choice in
    1)
        CRON_SCHEDULE="*/5 * * * *"
        DESCRIPTION="every 5 minutes"
        ;;
    2)
        CRON_SCHEDULE="0 * * * *"
        DESCRIPTION="every hour"
        ;;
    3)
        CRON_SCHEDULE="0 0 * * *"
        DESCRIPTION="every day at midnight"
        ;;
    4)
        CRON_SCHEDULE="0 0 * * 1"
        DESCRIPTION="every week on Monday at midnight"
        ;;
    *)
        echo "❌ Invalid choice"
        exit 1
        ;;
esac

# Create the cron job entry
CRON_JOB="$CRON_SCHEDULE cd $PROJECT_DIR && $VENV_PYTHON manage.py run_auto_backups >> $LOG_FILE 2>&1"

echo ""
echo "The following cron job will be added:"
echo "$CRON_JOB"
echo ""
echo "This will run $DESCRIPTION"
echo ""
read -p "Do you want to install this cron job? (y/n): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Installation cancelled."
    exit 0
fi

# Add to crontab
(crontab -l 2>/dev/null; echo ""; echo "# Community SH - Automatic Backups"; echo "$CRON_JOB") | crontab -

echo ""
echo "✅ Cron job installed successfully!"
echo ""
echo "Current crontab:"
crontab -l
echo ""
echo "To view backup logs, run:"
echo "  tail -f $LOG_FILE"
echo ""
echo "To test the backup manually, run:"
echo "  cd $PROJECT_DIR"
echo "  $VENV_PYTHON manage.py run_auto_backups"
echo ""
